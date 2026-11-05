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


def analyse_audio(x, sr=SR):
    """Features and events from mono samples. Times are seconds from the start of the audio."""
    import numpy as np
    if np.abs(x).max() < 10 ** (-60 / 20):
        return None, 'the audio is silent (is Rekordbox captured in OBS?)'
    hop, size = int(sr * HOP), int(sr * FRAME)
    n = max(1, 1 + (len(x) - size) // hop)
    pad = np.pad(x, (size // 2, size))
    win = np.hanning(size)
    freqs = np.fft.rfftfreq(size, 1 / sr)
    band = (freqs >= 30) & (freqs <= 150)
    bass, rms = np.empty(n), np.empty(n)
    for i in range(n):  # frame i is centred on i * HOP seconds
        f = pad[i * hop:i * hop + size]
        bass[i] = (np.abs(np.fft.rfft(f * win))[band] ** 2).sum()
        rms[i] = np.sqrt(np.mean(f ** 2))
    # The dips between kicks must not count: a 0.6 s moving max bridges them at 100 BPM and up,
    # then a 1 s moving mean evens it out.
    m = int(round(0.6 / HOP))
    peak = np.lib.stride_tricks.sliding_window_view(np.pad(bass, (m // 2, m - 1 - m // 2), mode='edge'), m).max(axis=1)
    k = int(round(1 / HOP))
    smooth = np.convolve(peak, np.ones(k) / k, mode='same')
    # "Full" bass is relative to the music around it: DJs mix tracks at very different bass levels.
    # F = 0.8 x the 80th percentile within a minute either side (one loud burst can't drag it up).
    F = np.empty(n)
    for i in range(0, n, 10):
        F[i:i + 10] = 0.8 * np.percentile(smooth[max(0, i - 450):i + 450], 80)
    full = smooth >= F
    silent = rms < 10 ** (-50 / 20)

    held = np.convolve(full, np.ones(20), mode='full')[19:len(full) + 19] >= 20  # a 2 s run starts here
    drops, last = [], None
    for i in range(1, n):
        if not full[i] or full[i - 1]:
            continue
        hold = slice(i, i + 80)  # 8 s: full on average, and most of the time
        if smooth[hold].mean() < F[i] or full[hold].mean() < 0.7:
            continue
        before = slice(max(0, i - 120), i)  # 12 s of music without a 2 s full stretch
        if held[max(0, i - 120):max(0, i - 20)].any() or silent[before].mean() > 0.5:
            continue
        t = i * HOP
        if last is not None and t - last < 6:
            continue
        # back to the first kick: first frame in the 2 s before where raw bass passes 0.5F
        lo = max(0, i - 20)
        first = next((j for j in range(lo, i + 1) if bass[j] >= 0.5 * F[j]), i)
        drops.append(round(first * HOP, 1))
        last = t
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
            'silence': silence, 'energy': energy, 'duration': round(len(x) / sr, 2)}, None


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
