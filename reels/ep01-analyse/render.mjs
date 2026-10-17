// node render.mjs            -> full video  (build/reel.mp4)
// node render.mjs 1.5 12 25  -> preview stills at those seconds (build/still_*.png)
import { chromium } from '/opt/node-tools/node_modules/playwright/index.mjs';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const dir = path.dirname(new URL(import.meta.url).pathname);
const timings = JSON.parse(fs.readFileSync(path.join(dir, 'build/timings.json'), 'utf8'));
const FPS = 30, DUR = 40;
const stills = process.argv.slice(2).map(Number);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
await page.addInitScript(t => { window.TIMINGS = t; }, timings);
await page.goto('file://' + path.join(dir, 'scene.html'));
await page.evaluate(() => document.fonts.ready);

if (stills.length) {
  for (const t of stills) {
    await page.evaluate(t => render(t), t);
    await page.screenshot({ path: path.join(dir, `build/still_${t}.png`) });
  }
} else {
  const ff = spawn('ffmpeg', ['-y', '-v', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-i', path.join(dir, 'build/vo.wav'), '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-pix_fmt', 'yuv420p',
    '-profile:v', 'high', '-r', String(FPS), '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart',
    path.join(dir, 'build/reel.mp4')], { stdio: ['pipe', 'inherit', 'inherit'] });
  for (let f = 0; f < FPS * DUR; f++) {
    await page.evaluate(t => render(t), f / FPS);
    const buf = await page.screenshot({ type: 'jpeg', quality: 95 });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if (f % 150 === 0) console.log(`frame ${f}/${FPS * DUR}`);
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
}
await browser.close();
