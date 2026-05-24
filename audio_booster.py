"""
Project inspired by coursework in Linear Systems (EE23)
at Tufts University, Spring 2026.

This script captures system audio using WASAPI loopback,
amplifies it, and routes to our real computer output plotting
the waveform in real-time as well.

cmd flag for help:
        python main.py -help

To avoid feedback loops, use a virtual audio cable (like VB-Cable):
1. Set Windows default audio output to 'CABLE Input'.
2. Run: python main.py -s and python main.py -o to find the corresponding device indices for the loopback source and real speakers, then use those indices in the command line arguments.
3. Run: python main.py -s [Cable_Index] -o [Real_Speaker_Index]

To install the virtual audio cable, you can download VB-Cable from its official website: https://vb-audio.com/Cable/.
Follow all installation instructions and restart your computer after installation. This will create a new audio device called "CABLE Input" that you can select as your default output device in Windows Sound settings. Then, you can use the loopback capture to grab audio from this virtual cable and route it to your real speakers without creating a feedback loop.
"""

import argparse
import collections
import queue
import sys

import numpy as np
import pyaudiowpatch as pyaudio
import sounddevice as sd
from matplotlib.animation import FuncAnimation
import matplotlib.pyplot as plt

def int_or_str(text):
    return int(text)

parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
)
parser.add_argument("-l", "--list-devices", action="store_true",
                    help="show available audio devices")
parser.add_argument("-s", "--source", type=int, default=None,
                    help="Loopback device index assignment flag (usage: -s [index])")
parser.add_argument("-o", "--output", type=int_or_str, default=None,
                    help="Output device index assignment flag (usage: -o [index])")
parser.add_argument("-g", "--gain", type=float, default=2.0,
                    help="Gain factor to apply to the audio (default: 2.0)")
parser.add_argument("-w", "--window", type=float, default=300,
                    help="Time window in milliseconds for the plot (default: 300ms)")
parser.add_argument("-i", "--interval", type=float, default=30,
                    help="Interval in milliseconds for plot updates (default: 30ms)")
parser.add_argument("-n", "--downsample", type=int, default=10,
                    help="Downsample factor for plotting (default: 10)")
args = parser.parse_args()

def find_loopback(p: pyaudio.PyAudio, preferred_output_index: int | None):
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)

        if preferred_output_index is None:
                preferred_output_index = wasapi["defaultOutputDevice"]
        
        target_name = p.get_device_info_by_index(preferred_output_index)["name"]
        
        first_loopback = None
        for i in range(p.get_device_count()):
                dev = p.get_device_info_by_index(i)
                if not (dev.get("isLoopbackDevice") and dev["hostApi"] == wasapi["index"]):
                       continue
                if first_loopback is None:
                       first_loopback = dev
                if target_name and target_name in dev["name"]:
                       return dev
        
        return first_loopback

def print_devices(p: pyaudio.PyAudio):
        print("\n****** PyAudio / WASAPI INPUT Devices (For -s) ******")
        for i in range(p.get_device_count()):
                d = p.get_device_info_by_index(i)
                if d.get("isLoopbackDevice"):
                    print(f" [{i}] {d['name']:<45} {int(d['defaultSampleRate'])} Hz [LOOPBACK]")

        print("\n****** SoundDevice OUTPUT Devices (For-o) ******")
        for d in sd.query_devices():
                if d["max_output_channels"] > 0:
                        idx = sd.query_devices().index(d)
                        print(f" [{idx}] {d['name']:<45} {int(d['default_samplerate'])} Hz")
        print()

p = pyaudio.PyAudio()

if args.list_devices:
        print_devices(p)
        p.terminate()
        sys.exit(0)

loopback_dev = find_loopback(p, args.source)
if loopback_dev is None:
        print("ERROR: No loopback device found! Run with -l to list devices and")
        print("check if WASAPI loopback is available.")
        p.terminate()
        sys.exit(1)

if args.output is None:
        out_dev_info = sd.query_devices(kind='output')
else:
        out_dev_info = sd.query_devices(args.output)
output_name = out_dev_info['name']

# If output == input
if output_name.split()[0] in loopback_dev['name']:
    print("\n" + "*"*60)
    print("Feedback Loop Detected!!\n")
    print(f"Input: {loopback_dev['name']}")
    print(f"Output: {output_name}")
    print("\nYou're trying to use the same device for input and output,")
    print("which will create an infinite loop")
    print("Install a Virtual Audio Cable (like VB-Cable)")
    print("to resolve this.")
    print("*"*60 + "\n")
    p.terminate()
    sys.exit(1)


SAMPLERATE = int(loopback_dev["defaultSampleRate"])
CHANNELS = min(loopback_dev["maxInputChannels"], 2)
CHUNK = 1024

print(f"\nStarting system audio capture and amplification...")

sample_buf = collections.deque()
plot_q = queue.Queue()

def loopback_callback(in_data, frame_count, time_info, status):
        audio = np.frombuffer(in_data, dtype=np.float32).copy()
        audio = audio.reshape(-1, CHANNELS)
        audio *= args.gain
        np.clip(audio, -1.0, 1.0, out=audio)

        sample_buf.append(audio)
        plot_q.put(audio[::args.downsample, 0:1])

        return (None, pyaudio.paContinue)

def output_callback(outdata: np.ndarray, frames: int, time, status):
        if status:
                print("output status:", status, file=sys.stderr)

        out = np.zeros((frames, CHANNELS), dtype=np.float32)
        needed = frames
        pos = 0

        while needed > 0 and sample_buf:
                chunk = sample_buf.popleft()
                take = min(len(chunk), needed)
                out[pos : pos + take] = chunk[:take]
                pos += take
                needed -= take
                if take < len(chunk):
                      sample_buf.appendleft(chunk[take:])

        outdata[:] = out

# Plotting
length = int(args.window * SAMPLERATE / (1000 * args.downsample))
plotdata = np.zeros((length, 1))

fig, ax = plt.subplots(figsize=(9, 2))
(line,) = ax.plot(plotdata[:, 0], color="#00D9FF", linewidth=0.8)
ax.axis((0, length, -1, 1))
ax.set_facecolor("#000000")
fig.patch.set_facecolor("#000000")
ax.set_yticks([0])
ax.yaxis.grid(True, color="#5C5C5C")
ax.tick_params(bottom=False, top=False, labelbottom=False,
               right=False, left=False, labelleft=False)
ax.set_title(f"System Audio x{args.gain} gain -- {SAMPLERATE} Hz",
             color="white", fontsize=9, pad=4)
fig.tight_layout(pad=0.3)

def update_plot(_frame):
        global plotdata
        while True:
                try:
                        data = plot_q.get_nowait()
                except queue.Empty:
                        break
                shift = len(data)
                plotdata = np.roll(plotdata, -shift, axis=0)
                plotdata[-shift:] = data
        line.set_ydata(plotdata[:, 0])
        return (line,)

out_stream = sd.OutputStream(
        device=args.output,
        samplerate=SAMPLERATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=CHUNK,
        callback=output_callback,
)

in_stream = p.open(
        format=pyaudio.paFloat32,
        channels=CHANNELS,
        rate=SAMPLERATE,
        input=True,
        input_device_index=loopback_dev["index"],
        frames_per_buffer=CHUNK,
        stream_callback=loopback_callback,
)

out_stream.start()
in_stream.start_stream()
ani = FuncAnimation(fig, update_plot, interval=args.interval,
                    blit=True, cache_frame_data=False)
plt.show()
in_stream.stop_stream()
in_stream.close()
out_stream.stop()
out_stream.close()
p.terminate()