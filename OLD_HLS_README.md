# Old HLS

`old_hls.m3u8` e a lista remota do player legado da TV Philco. Ela existe para desacoplar os canais do firmware: a TV baixa esta lista do GitHub quando a area de TV e aberta, entao trocar, remover ou adicionar um canal nao exige gerar um novo `.bin`.

## Perfil aceito

A lista deve conter somente canais lineares gratuitos/publicos que funcionem com a pilha antiga da TV e com o bridge local do firmware.

- Formato da lista: Extended M3U em UTF-8 (`.m3u8`).
- Uma entrada = uma linha `#EXTINF` seguida por uma URL HTTP/HTTPS.
- `group-title` obrigatorio. Grupos atuais: `Novelas`, `Series`, `Filmes` e `Humor`.
- Preferir URL HLS curta e direta terminando em `playlist.m3u8`, `index.m3u8` ou equivalente.
- HTTP e HTTPS sao permitidos; HTTPS e buscado pelo bridge moderno da V7.3, nao pelo OpenSSL legado do browser.
- Preferencia de midia: H.264/AVC + AAC em MPEG-TS, ate 1080p e 60 fps.
- Fontes com query/token obrigatorio, cookies especiais, headers customizados, SSAI complexo ou cadeias longas de redirect nao entram nesta lista.
- Nao usar DRM, Widevine, PlayReady, FairPlay, DASH-only, HEVC/H.265, AV1, VP9, AC-3/E-AC-3 ou HLS fMP4/CMAF (`#EXT-X-MAP`).
- AES-128, `#EXT-X-KEY` e streams com autenticacao/sessao devem ficar fora desta lista mesmo que o bridge consiga parte deles; o objetivo aqui e simplicidade e estabilidade.
- Canais dedicados a uma unica obra podem ser usados apenas quando forem desejados explicitamente. Para as categorias de nostalgia, priorizar grade rotativa.

## Como atualizar

Edite apenas `old_hls.m3u8`. A V7.3 busca:

`https://raw.githubusercontent.com/HyakkimaruPY/Lista-M3U.m3u/main/old_hls.m3u8`

Ao abrir novamente a area de TV, o player pede uma copia nova da lista com cache-buster. Se a rede/GitHub estiver indisponivel, o firmware mantem um fallback local para nao deixar a tela vazia.

## Bateria de testes

Ha dois niveis independentes:

1. `scripts/validate_streams.py`: usa `ffprobe` e `ffmpeg` para confirmar que o canal fornece audio e video decodificaveis.
2. `scripts/validate_old_hls.py`: verifica o perfil legado: sintaxe M3U, URL simples, redirect, manifesto HLS, codecs declarados, resolucao/FPS, ausencia de CMAF/fMP4, DRM/AES e segmentos obviamente incompativeis.

O workflow `Validar Old HLS` roda em PR/push que altere a lista e tambem diariamente. Falha estrutural ou incompatibilidade comprovada bloqueia a validacao. Timeout, DNS/regiao ou erro ambiguo do runner ficam como `uncertain`, sem apagar o canal automaticamente.

## Canais iniciais

Os canais iniciais desta lista foram confirmados manualmente como reproduziveis antes da inclusao: Tela Brasil TV, Reviva TV, Old School TV, Old Series, Urban Series, Classique TV, Urban Movies e Fora Tedio TV.
