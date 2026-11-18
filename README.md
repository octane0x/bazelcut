# bazelcut

Baixa **1 vídeo** (do YouTube ou de qualquer site que o [yt-dlp](https://github.com/yt-dlp/yt-dlp) suporta) e devolve **um `.zip` com um arquivo por corte**. Você informa o início, o fim e o título de cada corte.

```
entrada:  1 link  +  lista de "início fim título"
saída:    Título do vídeo.zip
            ├── 01 - Intro.mp4
            ├── 02 - Como funciona.mp4
            └── 03 - Créditos.mp4
```

## Requisitos

| Programa | Para quê |
|---|---|
| [`uv`](https://docs.astral.sh/uv/) | roda o script e instala o yt-dlp sozinho (não precisa de `pip install`) |
| `ffmpeg` | junta o vídeo baixado e faz os cortes |
| `node` **ou** `deno` | o yt-dlp precisa de um runtime JavaScript para baixar do YouTube |

No Arch: `sudo pacman -S uv ffmpeg nodejs`. No Debian/Ubuntu: `sudo apt install ffmpeg nodejs` e o `uv` pelo [instalador oficial](https://docs.astral.sh/uv/getting-started/installation/).

## Instalação

```bash
git clone https://github.com/octane0x/bazelcut.git
cd bazelcut
chmod +x bazelcut.py
ln -s "$PWD/bazelcut.py" ~/.local/bin/bazelcut   # ~/.local/bin precisa estar no PATH
```

Na primeira execução, o `uv` baixa o yt-dlp e guarda num ambiente isolado. Isso leva alguns segundos. Depois disso, ele não baixa de novo.

Sem o link no PATH, rode direto: `./bazelcut.py ...` ou `uv run --script bazelcut.py ...`.

## Uso

```bash
bazelcut LINK cortes.txt        # tempos num arquivo
bazelcut cortes.txt             # link escrito dentro do próprio arquivo
bazelcut LINK                   # cola os tempos no terminal e aperta Ctrl-D
bazelcut                        # cola o link e os tempos, depois Ctrl-D
bazelcut LINK < cortes.txt      # tempos pela entrada padrão
bazelcut -a LINK cortes.txt     # só áudio (mp3)
bazelcut -o meus.zip LINK cortes.txt
```

| Opção | Efeito |
|---|---|
| `-a`, `--audio` | gera **mp3** em vez de mp4 (baixa só o áudio, mais rápido) |
| `-o ZIP`, `--saida ZIP` | nome/caminho do zip (padrão: `<título do vídeo>.zip` na pasta atual) |
| `-h` | ajuda |

O caminho do zip pronto é a única coisa que sai no **stdout**. Todo o resto (progresso, avisos, erros) sai no stderr. Assim dá para usar em scripts:

```bash
zip=$(bazelcut LINK cortes.txt) && unzip "$zip"
```

## Formato dos tempos

Cada linha é um corte com **início**, **fim** e **título**:

```
https://www.youtube.com/watch?v=XXXXXXXXXXX
00:00 - 03:45 Intro
03:45 a 10:20.5 Como funciona
Créditos [1:02:10 - 1:05:00]
- 1:05:00 -> 1:06:30 — Bônus
```

- Tempos em `mm:ss` ou `h:mm:ss`, com fração opcional (`10:20.5` ou `10:20,5`). Os minutos podem passar de 59 sem hora: `100:00`.
- Entre os dois tempos pode vir `-`, `–`, `—`, `->`, `→`, `~`, `a`, `até`, `to`, ou só espaço.
- O título pode vir antes ou depois dos tempos, e os tempos podem estar entre `()` ou `[]`. Marcadores de lista (`-`, `*`, `•`) e separadores nas pontas são removidos.
- Se uma linha tiver mais de dois tempos, os dois primeiros são o corte. O resto fica no título: `00:00 - 01:00 Show às 10:30` vira o título `Show às 10:30`.
- Uma linha sem título vira `Parte N`.
- Linhas sem tempo, como cabeçalhos ou o próprio link, são ignoradas, e o programa avisa no terminal.
- O link pode estar em qualquer linha do texto ou ser passado como argumento. Tem que haver **exatamente 1**.
- Os cortes podem se sobrepor. Cada linha vira um arquivo independente.

Tudo é conferido **antes de baixar**. O programa para e mostra o número da linha quando:

- a linha tem só 1 tempo;
- o fim não vem depois do início;
- um tempo é inválido (ex.: `00:75`);
- há texto estranho entre os tempos;
- um corte passa do fim do vídeo (com 1 s de tolerância).

## O que sai

- **Vídeo (padrão):** MP4 com H.264 (CRF 18, `yuv420p`) e AAC 192 kbps. Abre em qualquer player ou editor.
- **Áudio (`-a`):** MP3 VBR (`-q:a 2`, ~190 kbps) com tags ID3v2.3.
- Nome de cada arquivo: `NN - Título.ext`. A numeração segue a ordem das linhas. Os caracteres proibidos em nomes de arquivo (`/ \ : | * ? " < >`) são trocados ou removidos.
- Cada arquivo leva os metadados `title` (o título do corte), `track` (`N/total`) e `album` (o título do vídeo).
- O zip é *stored*, ou seja, sem compressão, porque vídeo e áudio já vêm comprimidos. Os nomes com acento são gravados em UTF-8.

## Como funciona

1. O programa lê os tempos e o link e valida tudo.
2. O yt-dlp extrai as informações do vídeo. Com a duração em mãos, o programa confere se os cortes cabem no vídeo.
3. O yt-dlp baixa **uma vez** a melhor qualidade (`bv*+ba/b`, ou `bestaudio/best` com `-a`).
4. O ffmpeg faz cada corte. O vídeo é **recodificado**, e é isso que deixa o corte **exato no quadro**. Copiar sem recodificar só cortaria em keyframes e erraria o início por até alguns segundos.
5. Cada corte entra no zip e é apagado na hora. Assim, o espaço máximo em disco fica em cerca de vídeo + cortes.

Os arquivos temporários ficam numa pasta oculta `.bazelcut-*` **ao lado do zip**, e não no `/tmp`, que em muitas distros fica na RAM (tmpfs). Essa pasta é apagada no fim, mesmo quando há erro ou Ctrl-C. O zip só aparece quando tudo dá certo.

**Nunca sobrescreve:** se o zip padrão já existe, o novo vira `Título (2).zip`. Se o nome passado em `-o` já existe, o programa para com erro.

## Atualizar o yt-dlp

O YouTube muda com frequência e quebra o yt-dlp. Se o download falhar com um `ERROR:` do yt-dlp, atualize:

```bash
uv run -U --script /caminho/para/bazelcut.py -h
```

O próprio bazelcut mostra esse comando, com o caminho certo, quando o download falha.

## Limitações

- Recodificar leva tempo. Vídeos longos ou em 4K demoram (1 h em 1080p fica na casa de 10 a 20 min, conforme a CPU).
- Vídeos HDR saem em SDR de 8 bits sem *tone mapping*, então as cores podem ficar lavadas.
- Vídeos privados ou com restrição de idade precisam de login (cookies), e o bazelcut não trata isso.
- Playlists não são aceitas. Passe o link de um vídeo só. Um link `watch?v=...&list=...` funciona e baixa só o vídeo.

## Aviso

Use por sua conta. Baixe só conteúdo que você tem direito de baixar.
