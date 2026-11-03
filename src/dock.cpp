#include "dock.h"

#include "midi.h"
#include "session.h"

#include <obs-frontend-api.h>

#include <QLabel>
#include <QString>
#include <QTimer>
#include <QVBoxLayout>
#include <QWidget>

namespace {

QString status_text()
{
	QString t;
	auto devices = midi_devices();
	t += devices.empty() ? "No MIDI devices\n" : "MIDI devices:\n";
	for (auto &d : devices)
		t += QString("  %1%2\n").arg(QString::fromStdString(d.name), d.named ? "" : " (raw MIDI)");
	SessionStatus s = sessions_status();
	t += "\n";
	if (s.outputs.empty())
		t += "Not logging. Starts with Record or Go Live.\n";
	for (auto &o : s.outputs)
		t += QString("Logging %1\n").arg(QString::fromStdString(o));
	t += QString("Events: %1\n").arg(qulonglong(s.events));
	if (!s.error.empty())
		t += QString("\nError: %1\n").arg(QString::fromStdString(s.error));
	return t;
}

} // namespace

void dock_create()
{
	auto *w = new QWidget();
	auto *label = new QLabel(w);
	label->setTextFormat(Qt::PlainText);
	label->setWordWrap(true);
	label->setAlignment(Qt::AlignTop | Qt::AlignLeft);
	auto *layout = new QVBoxLayout(w);
	layout->addWidget(label);
	auto *timer = new QTimer(w);
	QObject::connect(timer, &QTimer::timeout, label, [label] { label->setText(status_text()); });
	timer->start(500);
	label->setText(status_text());
	obs_frontend_add_dock_by_id("rekordbox-log", "Rekordbox Log", w);
}
