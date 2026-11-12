#!/usr/bin/env python3
"""tests/nightly-prune.py: tools/nightly's prune on a fake tree (temp dir), one case per retention rule (Cal, 2026-11-12):
untested stays; after a nightly only baselines (play13, runs/play.sh default), the newest build on an active line, bisect
endpoints and builds inside an unresolved range stay; Cal's exe and anything while he plays stay; nothing outside
build/store/<exe>-<commit> and build/v111/nx2navi.play* is touched. Run: python3 tests/nightly-prune.py"""
import datetime, importlib.machinery, importlib.util, os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
today = datetime.date.today()
old = (today - datetime.timedelta(days=10)).isoformat()
new = today.isoformat()
# exe: (date, parent, nightly-tested)
BUILDS = {
    'play13': (old, '-', True),       # baseline
    'play20': (old, 'play13', True),  # tested, inner: deleted
    'play21': (old, 'play20', True),  # bisect endpoint a
    'play22': (old, 'play21', False), # inside the range, untested
    'play23': (old, 'play22', True),  # inside the range, tested (range a..b stays unresolved by the test's choice)
    'play24': (old, 'play23', True),  # bisect endpoint b
    'play25': (old, 'play24', True),  # default of runs/play.sh
    'play26': (old, 'play25', True),  # Cal's exe (newest play log)
    'play27': (old, 'play26', True),  # old leaf: deleted
    'play30': (old, 'play13', False), # untested: stays
    'play31': (new, 'play30', True),  # recent leaf: stays
    'play32': (old, 'play13', True),  # store column escapes build/store: left alone
    'other1': (old, 'play13', True),  # not nx2navi.play*: left alone
}


def tree():
    R = tempfile.mkdtemp(prefix='nightly-prune-')
    V, S = R + '/NX2navi/build/v111', R + '/NX2navi/build/store'
    for d in (V + '/logs', V + '/profile/save', V + '/shader-cache', S, R + '/runs', R + '/patches'):
        os.makedirs(d)
    open(V + '/pipeline-cache.bin', 'w').write('x')
    open(V + '/profile/save/progress.sav', 'w').write('x')
    open(V + '/shader-cache/a', 'w').write('x')
    open(R + '/runs/play.sh', 'w').write('export NX2NAVI_EXE="${NX2NAVI_EXE:-play25}"\n')
    rows = ['exe\tdate\tcommit\txlate\tbase\tparent\tpatches\tchanged\trun\tdefaults\tnote\tstore']
    res = ['date\tentry\texe\tcommit\txlate\tscenario\tmetric\tmean\tmin\tmax\tn\ttool\tsource\tknobs\tstatus\tenv\tcache\trecipe']
    for e, (date, parent, tested) in BUILDS.items():
        d = '%s/%s-c%s' % (S, e, e[-2:])
        os.makedirs(d)
        open(d + '/nx2navi.' + e, 'w').write('x' * 1000)
        os.chmod(d + '/nx2navi.' + e, 0o444); os.chmod(d, 0o555)
        open('%s/nx2navi.%s' % (V, e), 'w').write('x' * 1000)
        st = 'NX2navi/build/store/%s-c%s sha256:abc' % (e, e[-2:])
        if e == 'play32':
            st = 'NX2navi/build/v111/profile sha256:abc'
        rows.append('\t'.join([e, date, 'c' + e[-2:], 'x/1', 'b', parent, '', '+1', '', '', '', st]))
        if tested:
            res.append('\t'.join([date, 'su', e, 'c', 'x', 'field-west-standing', 'fps', '60', '59', '61', '3', 'suite nightly lab-run', 's', '', 'ok', 'e1', 'warm', 'r']))
    open(R + '/builds.tsv', 'w').write('\n'.join(rows) + '\n')
    open(R + '/results.tsv', 'w').write('\n'.join(res) + '\n')
    log = V + '/logs/play-20261111-000000.log'
    open(log, 'w').write('[host] build: entry=play exe=nx2navi.play26 commit=c26 xlate=x knobs=\n')
    os.utime(log, (time.time() - 3600, time.time() - 3600))
    return R


def load(R):
    os.environ['NIGHTLY_ROOT'] = R
    os.environ.pop('NIGHTLY_DRY', None)
    ld = importlib.machinery.SourceFileLoader('nightly', HERE + '/tools/nightly')
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader('nightly', ld))
    ld.exec_module(m)
    return m


FAIL = []


def check(what, ok):
    print('%s %s' % ('ok  ' if ok else 'FAIL', what))
    ok or FAIL.append(what)


def main():
    R = tree()
    V, S = R + '/NX2navi/build/v111', R + '/NX2navi/build/store'
    m = load(R)
    ranges = [('play21', 'play24', ['play22', 'play23'])]
    line, kept = m.prune(ranges)
    print(line)
    gone = lambda e: not os.path.exists('%s/nx2navi.%s' % (V, e)) and not any(x.startswith(e + '-') for x in os.listdir(S))
    there = lambda e: os.path.exists('%s/nx2navi.%s' % (V, e)) and any(x.startswith(e + '-') for x in os.listdir(S))
    check('tested inner build deleted (play20)', gone('play20'))
    check('tested old leaf deleted (play27)', gone('play27'))
    check('baseline play13 kept', there('play13'))
    check('runs/play.sh default kept (play25)', there('play25'))
    check("Cal's exe from the newest play log kept (play26)", there('play26'))
    check('untested kept (play30, play22)', there('play30') and there('play22'))
    check('recent leaf kept (play31)', there('play31'))
    check('bisect endpoints kept (play21, play24)', there('play21') and there('play24'))
    check('tested build inside an unresolved range kept (play23)', there('play23'))
    check('store path outside build/store left alone (play32)', there('play32') and os.path.isdir(V + '/profile/save'))
    check('non-play exe left alone (other1)', there('other1'))
    check('profile, shader cache, pipeline cache untouched',
          os.path.exists(V + '/profile/save/progress.sav') and os.path.exists(V + '/shader-cache/a') and os.path.exists(V + '/pipeline-cache.bin'))
    b = {l.split('\t')[0]: l.split('\t') for l in open(R + '/builds.tsv').read().split('\n')[1:] if l}
    check('builds.tsv store column marks the pruned row', b['play20'][11].startswith('pruned ') and ' sha256:' not in b['play20'][11])
    check('builds.tsv kept rows unchanged', b['play21'][11].endswith('sha256:abc'))
    check('report counts freed space', 'freed' in line and 'play20' in line)
    shutil.rmtree(R, ignore_errors=True)

    # Cal playing: a play log under 2 min old stops every deletion
    R = tree()
    V = R + '/NX2navi/build/v111'
    open(V + '/logs/play-20261112-000000.log', 'w').write('[host] build: entry=play exe=nx2navi.play31 commit=c xlate=x knobs=\n')
    m = load(R)
    line, _ = m.prune([])
    check('nothing pruned while a play log is under 2 min old', 'skipped' in line and os.path.exists(V + '/nx2navi.play20'))
    shutil.rmtree(R, ignore_errors=True)

    # dry run: reports, deletes nothing; assume_tested counts tonight's picks
    R = tree()
    V = R + '/NX2navi/build/v111'
    os.environ['NIGHTLY_DRY'] = '1'
    ld = importlib.machinery.SourceFileLoader('nightly2', HERE + '/tools/nightly')
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader('nightly2', ld))
    os.environ['NIGHTLY_ROOT'] = R
    ld.exec_module(m)
    line, _ = m.prune([], assume_tested=['play30'])
    check('dry run reports play20, play27 and play30 (counted as tested tonight)',
          line.startswith('would prune') and all(e in line for e in ('play20', 'play27', 'play30')))
    check('dry run deletes nothing', os.path.exists(V + '/nx2navi.play20') and os.path.exists(V + '/nx2navi.play27'))
    os.environ.pop('NIGHTLY_DRY')
    shutil.rmtree(R, ignore_errors=True)
    print('%d failed' % len(FAIL))
    sys.exit(1 if FAIL else 0)


main()
