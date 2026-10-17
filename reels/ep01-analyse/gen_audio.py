"""Synthesise the voiceover with Piper, place each line on the timeline,
and estimate word timings for the synced captions -> build/timings.json + build/vo.wav"""
import json, re, subprocess, sys, wave, os

MODEL = sys.argv[1]
OUT = "build"
os.makedirs(OUT, exist_ok=True)
SPEED = 0.86  # piper length_scale (<1 = faster)

# (start_s, display text, tts text or None)
LINES = [
    (0.15, "You wrote a great analysis, and still got only 7 points?", "You wrote a great analysis, and still got only seven points?"),
    (3.20, "Here's why.", None),
    (4.20, "Most students retell the text.", None),
    (6.30, "But 'analyse' means something else.", "But, analyse, means something else."),
    (10.10, "Analyse means explaining HOW the author creates an effect –", "Analyse means explaining how the author creates an effect."),
    (13.75, "language, structure, stylistic devices –", "language, structure, stylistic devices,"),
    (16.90, "and WHY it matters.", "and why it matters."),
    (20.70, "Don't write what the author says.", None),
    (24.60, "Write what the author DOES – and what effect it has.", "Write what the author does, and what effect it has."),
    (29.40, "See the difference?", None),
    (32.30, "Your formula: By using a device,", "Your formula: By using a device,"),
    (34.40, "the author does something – with an effect.", "the author does something, with an effect."),
    (37.20, "Save this – and follow for Episode 2!", "Save this, and follow for episode two!"),
]

def dur(p):
    with wave.open(p) as w:
        return w.getnframes() / w.getframerate()

def silences(p):
    r = subprocess.run(["ffmpeg", "-i", p, "-af", "silencedetect=n=-35dB:d=0.09", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r)]
    return list(zip(st, en))

words_out, clips = [], []
for i, (start, disp, tts) in enumerate(LINES):
    path = f"{OUT}/line{i:02d}.wav"
    subprocess.run([sys.executable, "-m", "piper", "-m", MODEL, "--length-scale", str(SPEED), "-f", path],
                   input=(tts or disp).encode(), check=True, capture_output=True)
    d = dur(path)
    sil = silences(path)
    # speech region = between leading and trailing silence
    s0 = sil[0][1] if sil and sil[0][0] < 0.02 else 0.0
    s1 = sil[-1][0] if sil and sil[-1][1] > d - 0.05 else d
    internal = [(a, b) for a, b in sil if a > s0 + 0.05 and b < s1 - 0.05]
    toks = disp.split()
    toks = [t for t in toks if t not in ("–",)]
    # boundaries after tokens ending with punctuation
    # pause boundaries come from the TTS text (its commas are what Piper pauses on)
    ref = (tts or disp).split()
    if len(ref) != len(toks):
        ref = toks
    punct_idx = [k for k, t in enumerate(ref[:-1]) if re.search(r"[,.:?!]$", t)]
    w = [len(re.sub(r"\W", "", t)) + 2.2 for t in toks]
    # segments
    segs = []
    if internal and len(internal) == len(punct_idx):
        anchors = [s0] + [x for a, b in internal for x in (a, b)] + [s1]
        cuts = [-1] + punct_idx + [len(toks) - 1]
        for j in range(len(cuts) - 1):
            segs.append((cuts[j] + 1, cuts[j + 1], anchors[2 * j], anchors[2 * j + 1]))
    else:
        segs.append((0, len(toks) - 1, s0, s1))
    for a, b, ta, tb in segs:
        tot = sum(w[a:b + 1]); t = ta
        for k in range(a, b + 1):
            dt = (tb - ta) * w[k] / tot
            words_out.append({"w": toks[k], "s": round(start + t, 3), "e": round(start + t + dt, 3), "line": i})
            t += dt
    clips.append((start, path, d))
    print(f"line {i:2d} start {start:5.2f} dur {d:4.2f} end {start+d:5.2f}  internal_sil={len(internal)} punct={len(punct_idx)}  {disp}")

# overlap check
for (a, _, da), (b, _, _) in zip(clips, clips[1:]):
    if a + da > b + 0.05:
        print(f"WARNING overlap: line at {a} ends {a+da:.2f} > next start {b}")

json.dump({"words": words_out, "lines": [l[1] for l in LINES]}, open(f"{OUT}/timings.json", "w"), indent=1)

inputs, filt = [], []
for k, (s, p, _) in enumerate(clips):
    inputs += ["-i", p]
    ms = int(s * 1000)
    filt.append(f"[{k}]adelay={ms}|{ms}[a{k}]")
filt.append("".join(f"[a{k}]" for k in range(len(clips))) + f"amix=inputs={len(clips)}:normalize=0,apad=whole_dur=40,atrim=0:40,"
            "highpass=f=70,acompressor=threshold=-18dB:ratio=3:attack=5:release=80,loudnorm=I=-14:TP=-1.5:LRA=7[out]")
subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "[out]", "-ar", "48000", "-ac", "2", f"{OUT}/vo.wav"], check=True)
print("ok", dur(f"{OUT}/vo.wav"))
