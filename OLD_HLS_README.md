# Old HLS

`old_hls.m3u8` e a grade remota do player legado da TV Philco. A TV baixa esta lista do GitHub ao abrir a area de TV, entao trocar, remover ou adicionar um canal nao exige gerar um novo `.bin`.

## Categorias reconhecidas pelo player

A playlist usa exatamente quatro valores em `group-title`:

- `Variedade`: novelas, culinaria, humor, canais gerais e tudo que nao seja exclusivamente filme, serie/sitcom ou CCTV.
- `Filmes`: canais cuja grade e essencialmente filmes.
- `Séries`: canais de series, sitcoms e programacao seriada.
- `CCTV`: canais CCTV gratuitos/diretos mantidos separadamente, independentemente do genero do conteudo.

A interface da TV mostra primeiro essas quatro categorias. Ao entrar em uma delas, mostra apenas seus canais; `Voltar` retorna primeiro para as categorias e depois para o menu Smart.

## Perfil aceito

- Extended M3U em UTF-8 (`.m3u8`).
- Uma entrada = `#EXTINF` + URL HTTP/HTTPS.
- `group-title` e obrigatorio e deve ser um dos quatro grupos acima.
- Preferir HLS H.264/AVC + AAC em MPEG-TS, ate 1080p/60 fps.
- URLs simples, sem token/query, continuam sendo o padrao.
- Uma fonte complexa ja comprovada pela bridge pode ser marcada explicitamente com `x-profile="bridge"`; hoje MasterChef Brasil e a excecao conhecida.
- Headers externos especiais continuam proibidos na lista remota.
- Nao usar DRM, Widevine, PlayReady, FairPlay, DASH-only, HEVC/H.265, AV1, VP9, AC-3/E-AC-3 ou HLS fMP4/CMAF (`#EXT-X-MAP`).
- AES-128 e outros `#EXT-X-KEY` permanecem fora deste perfil simples.

## CCTV

A categoria CCTV foi preenchida a partir dos canais `x-source="Free-TV"` da `cn.m3u` quando havia URL HLS direta, mais o CCTV-15 que ja era controle conhecido do firmware. Isso inclui CCTV-1, 2, 3, as tres variantes do CCTV-4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16 e 17. CCTV-5+ nao foi incluido porque a entrada atual da playlist chinesa nao pertence ao mesmo conjunto Free-TV direto.

## URL consumida pela V7.3

`https://raw.githubusercontent.com/HyakkimaruPY/Lista-M3U.m3u/main/old_hls.m3u8`

O navegador antigo nao acessa essa URL diretamente. A bridge Go faz o HTTPS, interpreta o M3U e entrega JSON local em `http://127.0.0.1:8765/c`.

## Bateria de testes

1. `scripts/validate_streams.py`: confirma audio e video com `ffprobe`/`ffmpeg`.
2. `scripts/validate_old_hls.py`: valida estrutura, categorias e perfil de compatibilidade legado.
3. `tests/test_old_hls.py`: impede regressao dos quatro grupos e das regras de URLs.

Timeout, DNS, bloqueio regional ou indisponibilidade momentanea continuam sendo `uncertain`; incompatibilidade estrutural comprovada falha o gate.
