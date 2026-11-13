#!/usr/bin/env python3
"""Switch 2 reference library: short public footage segments per game area, and "which reference frame looks like our shot".

Run it through `tools/ref` (the wrapper supplies python+opencv+ffmpeg+yt-dlp via nix shell). Commands:

  ref areas                          list area names, scene ids, how many segments each has
  ref add <url> [t=1:23] [len=40] [step=2] [area=<name>] [keep]
                                     download one short segment (video only, <=720p), cut a frame every <step> s into
                                     $REF_DIR/frames/<area>/<id>_<t>/, cache ORB features, append to tools/ref-index.json
  ref find <name>                    area (name, alias, scene id like 0x55): scene id, segments with URL&t=, frames dir.
                                     With `search` (or when it has no segments) lists YouTube candidates too.
  ref compare <shot.png> [scene]     best reference frames (scene = area name/alias/scene id; omit = all areas), top 3 as
                                     side-by-sides in the gallery; prints score lines
  ref seed <file>                    one `area url t=.. [len=..]` per line (# comments): run `add` for each
  ref sync                           re-fetch every segment of tools/ref-index.json that is missing locally

Data (frames, features, comparisons) lives in $REF_DIR (default ~/claude/nx2navi/refs) and is PRIVATE: never committed.
Git holds only this tool, tools/ref-areas.json (names, scene ids, search queries) and tools/ref-index.json (URL + t).
Gallery for `compare` output: $REF_GALLERY (default ~/claude/nx2navi/.lab/gallery).
"""
import json, os, re, subprocess, sys, shutil
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
REF_DIR = Path(os.environ.get('REF_DIR', Path.home() / 'claude/nx2navi/refs'))
GALLERY = Path(os.environ.get('REF_GALLERY', Path.home() / 'claude/nx2navi/.lab/gallery'))
AREAS_JSON = HERE / 'ref-areas.json'
INDEX_JSON = Path(os.environ.get('REF_INDEX', HERE / 'ref-index.json'))
FW = 640  # stored frame width


def die(msg):
    print('ref: ' + msg, file=sys.stderr)
    sys.exit(1)


def load_areas():
    return json.loads(AREAS_JSON.read_text())['areas']


def load_index():
    return json.loads(INDEX_JSON.read_text()) if INDEX_JSON.exists() else []


def save_index(idx):
    tmp = INDEX_JSON.with_suffix('.tmp')
    tmp.write_text(json.dumps(idx, indent=1) + '\n')
    tmp.rename(INDEX_JSON)


def norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


def resolve_area(name, areas):
    """Area dict for a name, alias, key or scene id ('0x55', '85'); exits when unknown."""
    n = norm(name)
    for a in areas:
        names = [a['key'], a['name']] + a.get('aliases', [])
        if n in [norm(x) for x in names]:
            return a
        if a.get('scene') is not None and n in (norm(a['scene']), norm(str(int(a['scene'], 16)))):
            return a
    hits = [a for a in areas if n and (n in norm(a['name']) or n in norm(a['key']))]
    if len(hits) == 1:
        return hits[0]
    die('unknown area %r (%s)' % (name, ', '.join(a['key'] for a in areas)))


def secs(t):
    """'1:23', '1h2m3s', '83', '83s' -> seconds."""
    t = str(t).strip()
    if ':' in t:
        v = 0
        for p in t.split(':'):
            v = v * 60 + float(p)
        return int(v)
    m = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?', t)
    if not m or not any(m.groups()):
        die('bad time %r' % t)
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def video_id(url):
    m = re.search(r'(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})', url)
    return m.group(1) if m else None


def url_time(url):
    m = re.search(r'[?&]t=([0-9hms:]+)', url)
    return secs(m.group(1)) if m else None


def run(cmd, tries=1, timeout=240, **kw):
    """Run cmd; yt-dlp section downloads sometimes hang, so each try is killed after `timeout` s."""
    r = None
    for _ in range(tries):
        try:
            r = subprocess.run(cmd, timeout=timeout, **kw)
        except subprocess.TimeoutExpired:
            continue
        if not r.returncode:
            return r
    if r is None or r.returncode:
        die('failed: ' + ' '.join(map(str, cmd[:4])) + ' ...')
    return r


def seg_dir(area, vid, t):
    return REF_DIR / 'frames' / area / ('%s_%d' % (vid, t))


def hud_mask(img):
    """255 where the picture is the world, 0 over the HUD (hearts and items top left, item top right, minimap bottom
    right, text box bottom): the HUD is identical in every shot and would dominate the feature matches."""
    h, w = img.shape[:2]
    m = np.full((h, w), 255, np.uint8)
    m[:int(.26 * h), :int(.34 * w)] = 0
    m[:int(.26 * h), int(.80 * w):] = 0
    m[int(.62 * h):, int(.70 * w):] = 0
    m[int(.72 * h):, int(.08 * w):int(.92 * w)] = 0
    return m


def orb_of(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    kp, des = cv2.ORB_create(1500).detectAndCompute(g, hud_mask(img))
    pts = np.array([k.pt for k in kp], np.float32).reshape(-1, 2)
    return pts, (des if des is not None else np.zeros((0, 32), np.uint8))


def hist_of(img):
    h = cv2.calcHist([cv2.cvtColor(img, cv2.COLOR_BGR2HSV)], [0, 1, 2], hud_mask(img), [8, 8, 8], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(h, h).flatten()


def grid_of(img):
    """8x4 Lab colour layout (where the sky, ground, bright and dark parts sit); a cheap scene-type cue."""
    return cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2Lab), (8, 4), interpolation=cv2.INTER_AREA).astype(np.float32).flatten()


def featurize(d):
    """Write feat.npz (ORB points/descriptors and HSV histogram per frame, HUD masked) for the frames in d; returns the count."""
    feats = {}
    jps = sorted(d.glob('f*.jpg'))
    for i, jp in enumerate(jps):
        img = cv2.imread(str(jp))
        pts, des = orb_of(img)
        feats['p%d' % i], feats['d%d' % i], feats['h%d' % i], feats['g%d' % i] = pts, des, hist_of(img), grid_of(img)
    np.savez_compressed(d / 'feat.npz', n=len(jps), **feats)
    return len(jps)


def cmd_reindex(args):
    """ref reindex: recompute every feat.npz from the stored frames (after changing the features or the HUD mask)."""
    for d in sorted((REF_DIR / 'frames').glob('*/*_*')):
        print(d, featurize(d))


def cmd_add(args, from_seed=False):
    kv = {'t': None, 'len': '40', 'step': '2', 'area': None}
    pos, keep = [], False
    for a in args:
        if a == 'keep':
            keep = True
        elif '=' in a and a.split('=', 1)[0] in kv:
            k, v = a.split('=', 1)
            kv[k] = v
        else:
            pos.append(a)
    if len(pos) != 1:
        die('usage: ref add <url> [t=..] [len=..] [step=..] [area=..] [keep]')
    url = pos[0]
    vid = video_id(url) or die('no YouTube video id in %r' % url)
    t0 = secs(kv['t']) if kv['t'] else (url_time(url) or 0)
    ln, step = int(kv['len']), float(kv['step'])
    if ln > 120:
        die('keep segments short (len<=120)')
    areas = load_areas()
    area = resolve_area(kv['area'], areas)['key'] if kv['area'] else 'unsorted'
    out = seg_dir(area, vid, t0)
    out.mkdir(parents=True, exist_ok=True)
    vdir = REF_DIR / 'tmp'
    vdir.mkdir(parents=True, exist_ok=True)
    vf = vdir / ('%s_%d.mp4' % (vid, t0))
    if vf.exists():
        vf.unlink()
    print('ref: %s  %s  t=%ds len=%ds' % (area, vid, t0, ln))
    run(tries=2, cmd=['yt-dlp', '-q', '--no-warnings', '--no-playlist', '-f',
         'bv*[height<=720][ext=mp4]/bv*[height<=720]/b[height<=720]',
         '--download-sections', '*%d-%d' % (t0, t0 + ln), '--force-keyframes-at-cuts',
         '-S', 'res:720', '-o', str(vdir / ('%s_%d.%%(ext)s' % (vid, t0))), '--merge-output-format', 'mp4',
         'https://www.youtube.com/watch?v=' + vid])
    got = sorted(vdir.glob('%s_%d.*' % (vid, t0)))
    if not got:
        die('download produced no file')
    src = got[0]
    for old in out.glob('*.jpg'):
        old.unlink()
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(src), '-vf', 'fps=1/%g,scale=%d:-2' % (step, FW), '-q:v', '3',
         str(out / 'f%03d.jpg')])
    n = featurize(out)
    if not keep:
        src.unlink()
    print('ref: %d frames in %s' % (n, out))
    if not from_seed or True:
        idx = load_index()
        e = {'area': area, 'url': 'https://www.youtube.com/watch?v=%s&t=%d' % (vid, t0), 'id': vid, 't': t0,
             'len': ln, 'step': step}
        idx = [x for x in idx if not (x['id'] == vid and x['t'] == t0)] + [e]
        save_index(idx)


def cmd_move(args):
    """ref move <from-area> <id>_<t> <to-area|drop>: re-file a probed segment (or drop it from disk and index)."""
    if len(args) != 3:
        die('usage: ref move <from-area> <id>_<t> <to-area|drop>')
    src = resolve_area(args[0], load_areas())['key'] if args[0] != 'unsorted' else 'unsorted'
    vid, t = args[1].rsplit('_', 1)
    d = seg_dir(src, vid, int(t))
    if not d.exists():
        die('no such segment ' + str(d))
    idx = [e for e in load_index() if not (e['id'] == vid and e['t'] == int(t) and e['area'] == src)]
    if args[2] == 'drop':
        shutil.rmtree(d)
    else:
        dst = resolve_area(args[2], load_areas())['key']
        e = next(e for e in load_index() if e['id'] == vid and e['t'] == int(t) and e['area'] == src)
        e['area'] = dst
        idx.append(e)
        (REF_DIR / 'frames' / dst).mkdir(parents=True, exist_ok=True)
        d.rename(seg_dir(dst, vid, int(t)))
    save_index(idx)


def cmd_batch(args):
    """ref batch <file>: run one ref command per line (e.g. a pile of `move`s)."""
    for line in Path(args[0]).read_text().splitlines():
        line = line.split('#', 1)[0].split()
        if line:
            CMDS[line[0]](line[1:])


def cmd_areas(args):
    idx = load_index()
    for a in load_areas():
        n = sum(1 for e in idx if e['area'] == a['key'])
        print('%-14s %-5s %-26s %d seg' % (a['key'], a.get('scene') or '-', a['name'], n))


def search_yt(q, n=6):
    r = subprocess.run(['yt-dlp', '--flat-playlist', '--print', '%(id)s|%(duration)s|%(title)s', 'ytsearch%d:%s' % (n, q)],
                       capture_output=True, text=True)
    return [l.split('|', 2) for l in r.stdout.splitlines() if l.count('|') >= 2]


def cmd_find(args):
    if not args:
        die('usage: ref find <area> [search]')
    do_search = 'search' in args
    args = [a for a in args if a != 'search']
    a = resolve_area(' '.join(args), load_areas())
    idx = [e for e in load_index() if e['area'] == a['key']]
    print('%s  scene %s  (%s)' % (a['name'], a.get('scene') or '?', a.get('time', '')))
    for e in idx:
        d = seg_dir(a['key'], e['id'], e['t'])
        have = len(list(d.glob('f*.jpg')))
        print('  %s  len %ss  %d frames%s' % (e['url'], e['len'], have, '' if have else '  (missing: ref sync)'))
    if do_search or not idx:
        for q in a.get('queries', ['Ocarina of Time Switch 2 ' + a['name']]):
            print('  search: ' + q)
            for vid, dur, title in search_yt(q):
                print('    https://www.youtube.com/watch?v=%s  %ss  %s' % (vid, dur, title))


def cmd_candidates(args):
    """ref candidates [area...]: gameplay-looking search hits (60 s - 40 min, no OST/music), for choosing seed segments."""
    areas = [resolve_area(a, load_areas()) for a in args] or load_areas()
    for a in areas:
        print('== ' + a['key'])
        seen = set()
        for q in a.get('queries', []) + ['Zelda Ocarina of Time Remake %s gameplay' % a['name']]:
            for vid, dur, title in search_yt(q, 8):
                try:
                    d = float(dur)
                except ValueError:
                    continue
                if vid in seen or not 60 <= d <= 2400 or re.search(r'OST|music|theme', title, re.I):
                    continue
                seen.add(vid)
                print('  %s %5ds %s' % (vid, d, title[:90]))


def cmd_sheet(args):
    """ref sheet <area>: contact sheet of every stored frame (every 2nd) into the gallery, to check a segment shows the area."""
    if args == ['all']:  # one tile per stored segment (its middle frame), labelled with the area
        tiles = []
        for a in load_areas():
            for sd in sorted((REF_DIR / 'frames' / a['key']).glob('*_*')):
                jps = sorted(sd.glob('f*.jpg'))
                if jps:
                    tiles.append(label(cv2.resize(cv2.imread(str(jps[len(jps) // 2])), (320, 180)), a['key'] + ' ' + sd.name[-4:]))
        while len(tiles) % 4:
            tiles.append(np.zeros_like(tiles[0]))
        GALLERY.mkdir(parents=True, exist_ok=True)
        out = GALLERY / 'ref-sheet-all.jpg'
        cv2.imwrite(str(out), np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]))
        print(out)
        return
    a = resolve_area(' '.join(args), load_areas())
    tiles = []
    for sd in sorted((REF_DIR / 'frames' / a['key']).glob('*_*')):
        for i, jp in enumerate(sorted(sd.glob('f*.jpg'))):
            if i % (1 if a['key'] == 'unsorted' else 3) == 0:
                im = cv2.resize(cv2.imread(str(jp)), (256, 144))
                tiles.append(label(im, '%s %d' % (sd.name[:8], i)))
    if not tiles:
        die('no frames for ' + a['key'])
    while len(tiles) % 4:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]
    GALLERY.mkdir(parents=True, exist_ok=True)
    out = GALLERY / ('ref-sheet-%s.jpg' % a['key'])
    cv2.imwrite(str(out), np.vstack(rows))
    print(out)


def read_feats(d):
    z = np.load(d / 'feat.npz')
    return [(z['p%d' % i], z['d%d' % i], z['h%d' % i], z['g%d' % i]) for i in range(int(z['n']))]


def match_score(fa, fb, bf):
    """ORB ratio-test matches then RANSAC homography inliers between two (pts, des, hist) triples."""
    (pa, da, ha, ga), (pb, db, hb, gb) = fa, fb
    hc = float(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL))
    gs = max(0.0, 1.0 - float(np.abs(ga - gb).mean()) / 60.0)  # colour layout similarity 0..1
    inl = 0
    if len(da) >= 8 and len(db) >= 8:
        good = [m[0] for m in bf.knnMatch(da, db, k=2) if len(m) == 2 and m[0].distance < 0.75 * m[1].distance]
        if len(good) >= 8:
            src = pa[[m.queryIdx for m in good]].reshape(-1, 1, 2)
            dst = pb[[m.trainIdx for m in good]].reshape(-1, 1, 2)
            _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
            inl = int(mask.sum()) if mask is not None else 0
    return hc, inl, gs


def label(img, text):
    cv2.rectangle(img, (0, 0), (img.shape[1], 26), (0, 0, 0), -1)
    cv2.putText(img, text, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def cmd_compare(args):
    if not args:
        die('usage: ref compare <shot.png> [scene]')
    shot = cv2.imread(args[0])
    if shot is None:
        die('cannot read ' + args[0])
    areas = load_areas()
    want = [resolve_area(' '.join(args[1:]), areas)] if len(args) > 1 else [a for a in areas if a['key'] != 'unsorted']
    h0 = FW * shot.shape[0] // shot.shape[1]
    small = cv2.resize(shot, (FW, h0), interpolation=cv2.INTER_AREA)
    fs = (*orb_of(small), hist_of(small), grid_of(small))
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    cands = []
    for a in want:
        for sd in sorted((REF_DIR / 'frames' / a['key']).glob('*_*')):
            if not (sd / 'feat.npz').exists():
                continue
            for i, ft in enumerate(read_feats(sd)):
                hc, inl, gs = match_score(fs, ft, bf)
                score = 0.3 * max(hc, 0) + 0.4 * gs + 0.3 * min(inl, 60) / 60
                cands.append((score, hc, inl, a['key'], sd, i, gs))
    if not cands:
        die('no reference frames for %s: run ref add / ref sync' % (args[1] if len(args) > 1 else 'any area'))
    cands.sort(key=lambda c: -c[0])
    GALLERY.mkdir(parents=True, exist_ok=True)
    stem = Path(args[0]).stem
    for rank, (score, hc, inl, key, sd, i, gs) in enumerate(cands[:3], 1):
        ref = cv2.imread(str(sd / ('f%03d.jpg' % (i + 1))))
        vid, t0 = sd.name.rsplit('_', 1)
        entry = next((e for e in load_index() if e['id'] == vid and e['t'] == int(t0)), None)
        step = entry['step'] if entry else 2
        ts = int(t0) + int(i * step)
        h = 540
        a = cv2.resize(shot, (shot.shape[1] * h // shot.shape[0], h), interpolation=cv2.INTER_AREA)
        b = cv2.resize(ref, (ref.shape[1] * h // ref.shape[0], h), interpolation=cv2.INTER_AREA)
        pic = np.hstack([label(a, 'ours: ' + stem), label(b, 'ref %s %s&t=%d' % (key, vid, ts))])
        out = GALLERY / ('ref-%s-%d-%s.png' % (stem, rank, key))
        cv2.imwrite(str(out), pic)
        print('%d score %.2f (hist %.2f, layout %.2f, orb inliers %d)  %s  https://www.youtube.com/watch?v=%s&t=%d  -> %s'
              % (rank, score, hc, gs, inl, key, vid, ts, out))


def cmd_seed(args):
    if len(args) != 1:
        die('usage: ref seed <file>')
    for line in Path(args[0]).read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        area, *rest = line.split()
        t = next((secs(r[2:]) for r in rest if r.startswith('t=')), 0)
        if (seg_dir(resolve_area(area, load_areas())['key'], video_id(rest[0]), t) / 'feat.npz').exists():
            continue  # already stored
        try:
            cmd_add(rest + ['area=' + area], True)
        except SystemExit:
            print('ref: seed line failed: ' + line, file=sys.stderr)


def cmd_sync(args):
    for e in load_index():
        if not list(seg_dir(e['area'], e['id'], e['t']).glob('f*.jpg')):
            cmd_add([e['url'], 't=%d' % e['t'], 'len=%d' % e['len'], 'step=%g' % e['step'], 'area=' + e['area']], True)


CMDS = {}


def main():
    if not os.environ.get('REF_NO_NICE'):  # CPU work shares the machine with Cal's game: low priority, spare cores
        os.nice(19)
        try:
            os.sched_setaffinity(0, {12, 13, 14, 15, 28, 29, 30, 31})
        except OSError:
            pass
    cmds = CMDS
    cmds.update({'add': cmd_add, 'areas': cmd_areas, 'find': cmd_find, 'compare': cmd_compare, 'seed': cmd_seed,
                 'sync': cmd_sync, 'candidates': cmd_candidates, 'sheet': cmd_sheet, 'reindex': cmd_reindex,
                 'move': cmd_move, 'batch': cmd_batch})
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(2)
    cmds[sys.argv[1]](sys.argv[2:])


if __name__ == '__main__':
    main()
