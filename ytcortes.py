#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["yt-dlp[default]"]
# ///
"""ytcortes: baixa 1 vídeo e entrega um .zip com um arquivo por corte (início, fim, título)."""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import NamedTuple

import yt_dlp

EXEMPLOS = """\
exemplos:
  ytcortes LINK cortes.txt        tempos num arquivo
  ytcortes cortes.txt             link dentro do próprio arquivo
  ytcortes LINK                   cola os tempos no terminal e aperta Ctrl-D
  ytcortes -a LINK cortes.txt     só áudio (mp3)

uma linha por corte: início, fim e título (h:mm:ss ou mm:ss; fração com . ou ,):
  00:00 - 03:45 Intro
  03:45 a 1:02:10.5 Parte longa
  Créditos [1:02:10 - 1:05:00]
linhas sem tempo são ignoradas (com aviso). nunca sobrescreve um zip existente.
"""

URL_RE = re.compile(r'https?://\S+|(?:www\.|m\.|music\.)?youtu(?:be\.com|\.be)/\S+')
# exige ":" (mm:ss ou h:mm:ss) para não confundir com números do título
TEMPO_RE = re.compile(r'(?<![\d:])(\d+):(\d{2})(?::(\d{2}))?(?:[.,](\d+))?(?![\d:])')
ENTRE_RE = re.compile(r'\s*(?:[-–—~>→=|,;/]+|até|ate|a|to)?\s*', re.IGNORECASE)
PONTAS = ' \t-–—~>→=|,;:•·*'
PROIBIDOS = {**dict.fromkeys(map(ord, '/\\:|'), '-'), **dict.fromkeys(map(ord, '*?"<>'), None),
             **dict.fromkeys(range(32), ' ')}


class Corte(NamedTuple):
    linha: int
    inicio: float
    fim: float
    titulo: str


def falhar(msg):
    sys.exit(f'ytcortes: {msg}')


def segundos(m):
    a, b, c, frac = m.groups()
    h, mi, s = (0, int(a), int(b)) if c is None else (int(a), int(b), int(c))
    if s > 59 or (c is not None and mi > 59):
        raise ValueError(m.group())
    return h * 3600 + mi * 60 + s + (float(f'0.{frac}') if frac else 0.0)


def hms(t):
    h, resto = divmod(t, 3600)
    m, s = divmod(resto, 60)
    txt = f'{int(m):02d}:{s:06.3f}'.rstrip('0').rstrip('.')
    return f'{int(h)}:{txt}' if h else txt


def nome_arquivo(txt, limite=180):
    txt = ' '.join(txt.translate(PROIBIDOS).split())
    return txt.encode()[:limite].decode(errors='ignore').strip(' .') or 'sem título'


def caminho_livre(p):
    alvo, i = p, 2
    while alvo.exists():
        alvo, i = p.with_name(f'{p.stem} ({i}){p.suffix}'), i + 1
    return alvo


def ler_entrada(itens):
    textos, links = [], []
    for item in itens:
        if URL_RE.fullmatch(item):
            links.append(item)
            continue
        try:
            textos.append(Path(item).read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeDecodeError) as e:
            falhar(f'não consegui ler {item}: {e}')
    if not textos:
        if sys.stdin.isatty():
            o_que = 'os tempos' if links else 'o link e os tempos'
            print(f'Cole {o_que} (uma linha por corte: "00:00 - 03:45 Título") e aperte Ctrl-D:',
                  file=sys.stderr)
        textos.append(sys.stdin.read())
    return '\n'.join(textos + links)  # links no fim: o nº da linha nos erros bate com o arquivo


def achar_link(texto):
    links = sorted({u.rstrip(').,;>]\'"') for u in URL_RE.findall(texto)})
    if len(links) != 1:
        falhar('preciso de exatamente 1 link de vídeo'
               + (f' (achei {len(links)}: {", ".join(links)})' if links else ' (não achei nenhum)'))
    return links[0] if '://' in links[0] else f'https://{links[0]}'


def ler_cortes(texto):
    cortes, erros = [], []
    for n, linha in enumerate(texto.splitlines(), 1):
        linha = URL_RE.sub(' ', linha)
        tempos = list(TEMPO_RE.finditer(linha))
        if not tempos:
            if linha.strip():
                print(f'aviso: linha {n} ignorada (sem tempo): {linha.strip()}', file=sys.stderr)
            continue
        if len(tempos) < 2:
            erros.append(f'linha {n}: só 1 tempo, falta o fim: {linha.strip()}')
            continue
        t1, t2 = tempos[:2]
        if not ENTRE_RE.fullmatch(linha[t1.end():t2.start()]):
            erros.append(f'linha {n}: não entendi o que há entre os dois tempos: {linha.strip()}')
            continue
        try:
            ini, fim = segundos(t1), segundos(t2)
        except ValueError as e:
            erros.append(f'linha {n}: tempo inválido {e}')
            continue
        if fim <= ini:
            erros.append(f'linha {n}: o fim ({hms(fim)}) não vem depois do início ({hms(ini)})')
            continue
        antes, depois = linha[:t1.start()].rstrip(), linha[t2.end():].lstrip()
        if antes.endswith(('(', '[')) and depois.startswith((')', ']')):  # "Título (00:00 - 03:45)"
            antes, depois = antes[:-1], depois[1:]
        titulo = ' '.join(p for p in (antes.strip(PONTAS), depois.strip(PONTAS)) if p)
        cortes.append(Corte(n, ini, fim, titulo or f'Parte {len(cortes) + 1}'))
    if erros:
        falhar('tempos com problema:\n  ' + '\n  '.join(erros))
    if not cortes:
        falhar('nenhum corte encontrado (uma linha por corte: "00:00 - 03:45 Título")')
    return cortes


def cortar(origem, destino, c, faixa, album, audio):
    cmd = ['ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'error', '-stats',
           '-ss', f'{c.inicio:.3f}', '-i', origem, '-t', f'{c.fim - c.inicio:.3f}',
           '-map_metadata', '-1', '-map_chapters', '-1',
           '-metadata', f'title={c.titulo}', '-metadata', f'track={faixa}', '-metadata', f'album={album}']
    if audio:
        cmd += ['-map', '0:a:0', '-c:a', 'libmp3lame', '-q:a', '2', '-id3v2_version', '3']
    else:  # reencoda para cortar no quadro exato (cópia direta só corta em keyframe)
        cmd += ['-map', '0:v:0', '-map', '0:a:0?', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart']
    if subprocess.run([*cmd, destino]).returncode:
        falhar(f'o ffmpeg falhou no corte da linha {c.linha}')


def gerar_zip(video, cortes, pasta, album, audio):
    ext = 'mp3' if audio else 'mp4'
    total = len(cortes)
    largura = max(2, len(str(total)))
    zip_tmp = pasta / 'saida.zip'
    with zipfile.ZipFile(zip_tmp, 'w', zipfile.ZIP_STORED) as zf:  # mídia já vem comprimida
        for i, c in enumerate(cortes, 1):
            nome = f'{i:0{largura}d} - {nome_arquivo(c.titulo)}.{ext}'
            print(f'[{i}/{total}] {nome}  ({hms(c.inicio)} → {hms(c.fim)})', file=sys.stderr)
            arquivo = pasta / nome
            cortar(video, arquivo, c, f'{i}/{total}', album, audio)
            zf.write(arquivo, nome)
            arquivo.unlink()  # libera espaço: cada corte já está no zip
    return zip_tmp


def main():
    ap = argparse.ArgumentParser(
        prog='ytcortes', epilog=EXEMPLOS, formatter_class=argparse.RawDescriptionHelpFormatter,
        description='Baixa 1 vídeo (YouTube ou outro site do yt-dlp) e entrega um .zip com um arquivo por corte.')
    ap.add_argument('entrada', nargs='*', metavar='LINK|ARQUIVO',
                    help='link do vídeo e/ou arquivo com os tempos; sem arquivo, lê os tempos da entrada padrão')
    ap.add_argument('-o', '--saida', type=Path, metavar='ZIP',
                    help='zip de saída (padrão: "<título do vídeo>.zip" na pasta atual)')
    ap.add_argument('-a', '--audio', action='store_true', help='só áudio, em mp3 (padrão: vídeo mp4 H.264)')
    args = ap.parse_args()

    if not shutil.which('ffmpeg'):
        falhar('ffmpeg não encontrado no PATH')
    texto = ler_entrada(args.entrada)
    link = achar_link(texto)
    cortes = ler_cortes(texto)
    if args.saida and args.saida.exists():
        falhar(f'{args.saida} já existe; escolha outro nome')
    pasta = args.saida.resolve().parent if args.saida else Path.cwd()
    if not pasta.is_dir():
        falhar(f'a pasta {pasta} não existe')

    print(f'{len(cortes)} cortes:', file=sys.stderr)
    for c in cortes:
        print(f'  {hms(c.inicio):>10} → {hms(c.fim):<10} {c.titulo}', file=sys.stderr)

    # temporário ao lado do zip (disco), não em /tmp (tmpfs = RAM)
    with tempfile.TemporaryDirectory(prefix='.ytcortes-', dir=pasta) as tmp:
        opcoes = {
            'noplaylist': True,
            'format': 'bestaudio/best' if args.audio else 'bv*+ba/b',
            'paths': {'home': tmp},
            'outtmpl': 'video.%(ext)s',
            'js_runtimes': {'deno': {}, 'node': {}},  # o yt-dlp só liga o deno por padrão
            'logtostderr': True,  # stdout fica só com o caminho do zip
        }
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            info = ydl.extract_info(link, download=False)
            if info.get('_type') == 'playlist':
                falhar('o link é de uma playlist; passe o link de 1 vídeo')
            # confere os tempos antes de baixar; tolera 1 s (a duração vem arredondada)
            duracao = info.get('duration')
            fora = [c for c in cortes if duracao and c.fim > duracao + 1]
            if fora:
                falhar(f'o vídeo tem {hms(duracao)}; passam do fim: '
                       + ', '.join(f'linha {c.linha} ({hms(c.fim)})' for c in fora))
            titulo = info.get('title') or info['id']
            saida = args.saida or caminho_livre(pasta / f'{nome_arquivo(titulo)}.zip')
            info = ydl.process_ie_result(info, download=True)
        video = info['requested_downloads'][0]['filepath']
        os.replace(gerar_zip(video, cortes, Path(tmp), titulo, args.audio), saida)
    print(f'pronto: {len(cortes)} arquivos em', file=sys.stderr)
    print(saida)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nytcortes: cancelado', file=sys.stderr)
        sys.exit(130)
    except yt_dlp.utils.DownloadError:
        sys.exit('ytcortes: o yt-dlp falhou (erro acima). Se o YouTube mudou algo, atualize o yt-dlp:\n'
                 f'  uv run -U --script {Path(__file__).resolve()} -h')
