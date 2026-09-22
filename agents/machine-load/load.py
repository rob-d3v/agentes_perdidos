#!/usr/bin/env python3
"""machine-load — what is eating RAM and CPU on this Windows PC, and what is safe to close.

Sibling of `disk-audit`/`faxineiro`, which answer "where did my DISK go". This one
answers "where did my MEMORY go, and why is everything slow right now".

Written after a real incident: a workstation hit 95% RAM with 0.7 GB free during a
long AI-assisted session. Nothing malicious was running. The answer was 32 `claude`
processes (4.4 GB), 8 `node` (2.4 GB), 18 `chrome` (1.8 GB) and 123 small
`python`/`bash`/`conhost` processes — agent tooling accumulating faster than it was
reaped. The problem was never that something was wrong; it was that nobody had
printed the list.

Stdlib only. Python 3.8+. Windows-first (uses ctypes + WMI via PowerShell fallback);
degrades to /proc on Linux.

    python load.py                 # report
    python load.py --top 25        # deeper list
    python load.py --stale 240     # flag processes older than N minutes
    python load.py --json          # machine-readable

IT NEVER KILLS ANYTHING. It prints what it would suggest closing and why, and the
human closes it. A process list is a bad basis for automated killing: the biggest
consumer is often the editor with unsaved work in it.
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from collections import defaultdict

# Grupos que costumam dominar uma maquina de desenvolvimento assistida por IA.
# Nomeados para que o relatorio diga "ferramenta de IA: 8.6 GB" em vez de listar
# trinta linhas que o leitor precisa somar de cabeca.
FAMILIES = {
    'IA / agentes': {'claude', 'node', 'uv', 'python', 'pythonw', 'bash', 'conhost', 'py'},
    'Navegador': {'chrome', 'msedge', 'msedgewebview2', 'firefox', 'brave'},
    'Editor / IDE': {'code', 'devenv', 'idea64', 'pycharm64', 'rider64', 'sublime_text'},
    'Contêineres': {'docker desktop', 'com.docker.backend', 'com.docker.build', 'vmmem', 'vmmemwsl', 'dockerd'},
    'Sistema': {'svchost', 'explorer', 'dwm', 'csrss', 'lsass', 'services', 'registry',
                'memcompression', 'system', 'wininit', 'winlogon', 'fontdrvhost', 'sihost',
                'ctfmon', 'runtimebroker', 'searchhost', 'startmenuexperiencehost',
                'shellexperiencehost', 'textinputhost', 'widgets', 'widgetservice'},
    'Antivírus': {'msmpeng', 'nissrv', 'securityhealthservice', 'mpdefendercoreservice'},
}
PRESSURE_WARN = 80
PRESSURE_CRIT = 90


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]


def memory():
    if os.name != 'nt':
        try:
            info = {}
            with open('/proc/meminfo') as handle:
                for line in handle:
                    key, _, rest = line.partition(':')
                    info[key] = int(rest.split()[0]) * 1024
            total, avail = info['MemTotal'], info.get('MemAvailable', info['MemFree'])
        except (OSError, KeyError, ValueError):
            return None
    else:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        total, avail = status.ullTotalPhys, status.ullAvailPhys
    gb = 1024 ** 3
    return {'total_gb': round(total / gb, 1), 'free_gb': round(avail / gb, 1),
            'used_percent': round(100 * (total - avail) / total)}


def processes():
    """name, pid, working set, age in minutes. PowerShell because Win32 process
    enumeration through pure ctypes is a lot of code for the same answer."""
    if os.name != 'nt':
        return _proc_linux()
    script = ("Get-Process | ForEach-Object { try { $s=$_.StartTime } catch { $s=$null }; "
              "[PSCustomObject]@{n=$_.ProcessName;p=$_.Id;w=$_.WorkingSet64;"
              "t=if($s){[int]((Get-Date)-$s).TotalMinutes}else{-1}} } | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                             capture_output=True, text=True, timeout=90,
                             encoding='utf-8', errors='replace')
    except (subprocess.TimeoutExpired, OSError):
        return []
    if out.returncode != 0 or not out.stdout.strip():
        return []
    try:
        rows = json.loads(out.stdout)
    except ValueError:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    return [{'name': r['n'], 'pid': r['p'], 'bytes': r['w'] or 0, 'age_min': r['t']} for r in rows]


def _proc_linux():
    rows = []
    for pid in filter(str.isdigit, os.listdir('/proc')):
        try:
            with open(f'/proc/{pid}/status') as handle:
                name = rss = None
                for line in handle:
                    if line.startswith('Name:'):
                        name = line.split()[1]
                    elif line.startswith('VmRSS:'):
                        rss = int(line.split()[1]) * 1024
            if name:
                age = int((time.time() - os.path.getmtime(f'/proc/{pid}')) / 60)
                rows.append({'name': name, 'pid': int(pid), 'bytes': rss or 0, 'age_min': age})
        except (OSError, ValueError, IndexError):
            continue
    return rows


def family_of(name):
    low = name.lower()
    for label, members in FAMILIES.items():
        if low in members:
            return label
    return 'Outros'


def report(procs, stale_min, top):
    by_name, by_family = defaultdict(lambda: {'n': 0, 'bytes': 0, 'stale': 0}), defaultdict(int)
    for proc in procs:
        entry = by_name[proc['name']]
        entry['n'] += 1
        entry['bytes'] += proc['bytes']
        if proc['age_min'] >= stale_min:
            entry['stale'] += 1
        by_family[family_of(proc['name'])] += proc['bytes']
    programs = sorted(({'name': k, **v} for k, v in by_name.items()),
                      key=lambda x: -x['bytes'])
    return programs[:top], sorted(by_family.items(), key=lambda kv: -kv[1])


# Nunca sugerir fechar isto. Um `svchost` parado ha horas e' um servico do
# Windows fazendo o trabalho dele, nao uma sessao esquecida: a primeira versao
# deste agente sugeriu "fechar 83 svchost para recuperar 0.9 GB", que e' um
# conselho ativamente nocivo. "Ha muito tempo aberto" so significa desperdicio
# em processo que o USUARIO abriu.
NEVER_SUGGEST = {'Sistema', 'Antivírus', 'Antivirus'}


def advise(mem, programs, stale_min):
    """Conselhos concretos, com numero. 'Feche coisas' nao e' conselho."""
    tips = []
    if not mem:
        return tips
    if mem['used_percent'] >= PRESSURE_WARN:
        for prog in programs:
            if family_of(prog['name']) in NEVER_SUGGEST:
                continue
            if prog['stale'] >= 3 and prog['bytes'] > 300 * 1024 ** 2:
                share = prog['bytes'] / prog['n'] / 1024 ** 2
                tips.append(
                    f"{prog['stale']} de {prog['n']} processos `{prog['name']}` estao parados ha mais "
                    f"de {stale_min} min, ~{share:.0f} MB cada. Fechar as sessoes antigas "
                    f"devolve ~{prog['stale']*share/1024:.1f} GB.")
        big = [p for p in programs if p['n'] >= 25 and p['bytes'] > 200 * 1024 ** 2
               and family_of(p['name']) not in NEVER_SUGGEST]
        for prog in big:
            tips.append(f"`{prog['name']}` tem {prog['n']} instancias. Numero assim costuma ser "
                        f"acumulo de ferramenta, nao uso real — vale checar quem as cria.")
    if not tips and mem['used_percent'] >= PRESSURE_WARN:
        tips.append('Memoria alta, mas nenhum acumulo obvio: o consumo esta distribuido em '
                    'processos vivos e em uso. Fechar algo aqui custa trabalho de verdade.')
    return tips


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--top', type=int, default=15)
    parser.add_argument('--stale', type=int, default=240, help='Minutos para considerar parado.')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)

    mem, procs = memory(), processes()
    if not procs:
        print('Nao consegui enumerar processos.', file=sys.stderr)
        return 1
    programs, families = report(procs, args.stale, args.top)
    tips = advise(mem, programs, args.stale)

    if args.json:
        print(json.dumps({'memory': mem, 'programs': programs,
                          'families': families, 'advice': tips}, indent=2))
        return 0

    mb = lambda b: b / 1024 ** 2
    if mem:
        level = ('CRITICA' if mem['used_percent'] >= PRESSURE_CRIT else
                 'ALTA' if mem['used_percent'] >= PRESSURE_WARN else 'ok')
        print(f"RAM {mem['used_percent']}% [{level}] — {mem['free_gb']} GB livres "
              f"de {mem['total_gb']} GB\n")
    print('POR FAMILIA')
    for label, total in families:
        print(f"  {label:<16} {mb(total):>8.0f} MB")
    print(f'\nPOR PROGRAMA (top {args.top})')
    print(f"  {'programa':<24}{'inst':>5}{'MB':>9}   parados >{args.stale}min")
    for prog in programs:
        flag = f"  {prog['stale']}" if prog['stale'] else ''
        print(f"  {prog['name'][:24]:<24}{prog['n']:>5}{mb(prog['bytes']):>9.0f}{flag}")
    if tips:
        print('\nO QUE FAZER')
        for tip in tips:
            print(f'  - {tip}')
    print('\nNada foi encerrado. Este agente so relata; fechar e decisao sua — o maior '
          'consumidor costuma ser o editor com trabalho nao salvo dentro.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
