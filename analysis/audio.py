"""Drops, breakdowns, silence and energy from the recording's audio (needs numpy and ffmpeg)."""
import shutil
import subprocess
from pathlib import Path

SR = 11025
HOP = 0.1          # seconds between frames
FRAME = 0.2        # seconds of audio per frame
VIDEO_EXTS = ('.mov', '.mp4', '.mkv', '.flv', '.ts', '.m4v')


def find_video(log_path):
    base = log_path.name.removesuffix('.rekordbox.jsonl')
    for ext in VIDEO_EXTS:
        p = log_path.with_name(base + ext)
        if p.exists():
            return p
    return None


def read_audio(video):
    """Mono float samples at SR, or (None, reason)."""
    if shutil.which('ffmpeg') is None:
        return None, 'ffmpeg not installed'
    import numpy as np
    run = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-vn', '-ac', '1', '-ar', str(SR),
                          '-f', 'f32le', '-'], capture_output=True)
    if run.returncode != 0:
        return None, f'ffmpeg could not read {video.name}: {run.stderr.decode(errors="replace").strip()[:200]}'
    x = np.frombuffer(run.stdout, dtype='<f4')
    if x.size == 0:
        return None, f'{video.name} has no audio track'
    return x, None


def spans(mask, min_frames):
    """(start, end) frame indices of runs of True at least min_frames long."""
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            if j - i >= min_frames:
                out.append((i, j))
            i = j
        else:
            i += 1
    return out


def features(x, sr=SR):
    """Per frame (every HOP seconds, centred): bass energy (30-150 Hz) and RMS."""
    import numpy as np
    hop, size = int(sr * HOP), int(sr * FRAME)
    n = max(1, 1 + (len(x) - size) // hop)
    pad = np.pad(x, (size // 2, size))
    win = np.hanning(size)
    freqs = np.fft.rfftfreq(size, 1 / sr)
    band = (freqs >= 30) & (freqs <= 150)
    bass, rms = np.empty(n), np.empty(n)
    for i in range(n):
        f = pad[i * hop:i * hop + size]
        bass[i] = (np.abs(np.fft.rfft(f * win))[band] ** 2).sum()
        rms[i] = np.sqrt(np.mean(f ** 2))
    return bass, rms


def analyse_audio(x, sr=SR):
    """Features and events from mono samples. Times are seconds from the start of the audio."""
    import numpy as np
    if np.abs(x).max() < 10 ** (-60 / 20):
        return None, 'the audio is silent (is Rekordbox captured in OBS?)'
    bass, rms = features(x, sr)
    return events(bass, rms, round(len(x) / sr, 2)), None


def events(bass, rms, duration):
    """Drops, breakdowns, silence and energy from the per-frame bass and RMS."""
    import numpy as np
    n = len(bass)
    # The dips between kicks must not count: a 0.6 s moving max bridges them at 100 BPM and up,
    # then a 1 s moving mean evens it out.
    m = int(round(0.6 / HOP))
    peak = np.lib.stride_tricks.sliding_window_view(np.pad(bass, (m // 2, m - 1 - m // 2), mode='edge'), m).max(axis=1)
    k = int(round(1 / HOP))
    smooth = np.convolve(peak, np.ones(k) / k, mode='same')
    # "Full" bass is relative to the music around it: DJs mix tracks at very different bass levels.
    # F = 0.8 x the 80th percentile within 45 s either side (one loud burst can't drag it up).
    F = np.empty(n)
    for i in range(0, n, 10):
        F[i:i + 10] = 0.8 * np.percentile(smooth[max(0, i - 450):i + 450], 80)
    drops = find_drops(smooth, bass, rms)
    after = int(drops[0] / HOP) if drops else n
    quiet = np.zeros(n, bool)
    quiet[after:] = smooth[after:] < 0.3 * F[after:]
    breakdowns = [(round(a * HOP, 1), round(b * HOP, 1)) for a, b in spans(quiet, 160)]
    silence = [(round(a * HOP, 1), round(b * HOP, 1)) for a, b in spans(rms < 10 ** (-50 / 20), 10)]
    per_min = int(round(60 / HOP))
    minutes = [float(smooth[i:i + per_min].mean()) for i in range(0, n, per_min)]
    top = max(minutes) or 1.0
    energy = [min(7, int(m / top * 7 + 0.5)) for m in minutes]
    return {'F': F, 'smooth': smooth, 'drops': drops, 'breakdowns': breakdowns,
            'silence': silence, 'energy': energy, 'duration': duration}


JUMP_BASS = 8    # dB: bass in the 3 s after vs the 3 s before
JUMP_LOUD = 5    # dB: loudness, the same way
REHIT = 6        # dB: if the bass 5-12 s before was within this of the new level, it's the same drop


def find_drops(smooth, bass, rms):
    """A drop is a jump: after the energy falls away, the bass and the loudness come back much higher
    and stay there. Measured on a real set (drops at 1:30, 2:48, 4:36): bass +10 to +50 dB, loudness
    +7 to +12 dB. Returns the first kick of each drop, in seconds."""
    import numpy as np
    n = len(smooth)
    music = rms >= 10 ** (-50 / 20)
    cb = np.concatenate([[0], np.cumsum(smooth)])
    cl = np.concatenate([[0], np.cumsum(rms ** 2)])

    def mean_db(c, a, b):
        a, b = max(0, a), min(n, b)
        return 10 * np.log10(max((c[b] - c[a]) / (b - a), 1e-12)) if b > a else -120.0

    hits = []
    for i in range(30, n - 30):
        after_b, before_b = mean_db(cb, i, i + 30), mean_db(cb, i - 30, i)
        if after_b - before_b < JUMP_BASS:
            continue
        # it holds: every second from 3 to 10 s on stays at least 5 dB above where it was
        if any(mean_db(cb, j, j + 10) < before_b + JUMP_BASS - 3 for j in range(i + 30, min(n, i + 100), 10)):
            continue
        if mean_db(cl, i, i + 30) - mean_db(cl, i - 30, i) < JUMP_LOUD:
            continue
        if music[max(0, i - 50):max(0, i - 10)].mean() < 0.8:  # out of music, not the set starting
            continue
        if mean_db(cb, i - 120, i - 50) > after_b - REHIT:  # it was already there: a re-hit
            continue
        hits.append((i, after_b - before_b, after_b))
    drops, group = [], []
    for h in hits + [None]:
        if group and (h is None or h[0] - group[-1][0] > 80):
            i, _, after_b = max(group, key=lambda g: g[1])
            # the first kick: first frame from 3 s before where raw bass is within 5 dB of the new level
            level = 10 ** ((after_b - 5) / 10)
            first = next((j for j in range(max(0, i - 30), min(n, i + 30)) if bass[j] >= level), i)
            if not drops or first * HOP - drops[-1] >= 6:
                drops.append(round(first * HOP, 1))
            group = []
        if h is not None:
            group.append(h)
    return drops


def frame(audio, t):
    return min(len(audio['smooth']) - 1, max(0, int(round(t / HOP))))


def bass_at(audio, t):
    return float(audio['smooth'][frame(audio, t)])


def full_at(audio, t):
    """The "full bass" level at time t."""
    return float(audio['F'][frame(audio, t)])


def load(log_path, video=None):
    """(audio dict, video path, reason it was skipped)."""
    video = Path(video) if video else find_video(log_path)
    if video is None:
        return None, None, 'no video next to the log (pass --video)'
    try:
        import numpy  # noqa: F401
    except ImportError:
        return None, video, 'numpy not installed (pip install numpy)'
    x, why = read_audio(video)
    if x is None:
        return None, video, why
    audio, why = analyse_audio(x)
    return audio, video, why
