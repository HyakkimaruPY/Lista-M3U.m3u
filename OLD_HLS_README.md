# Old HLS

`old_hls.m3u8` e a grade remota do player legado da TV Philco. A TV baixa esta lista do GitHub ao abrir a area de TV, entao trocar, remover ou adicionar um canal nao exige gerar um novo `.bin`.

## Categorias

A partir da V7.3.2 DYNCAT, as categorias deixam de ser fixas no firmware: a interface descobre automaticamente os valores distintos de `group-title` presentes na playlist. Portanto, criar ou remover uma categoria passa a ser somente uma alteracao no M3U.

Grupos atuais:

- `Variedade`: novelas, culinaria, humor, canais gerais e tudo que nao seja exclusivamente filme, serie/sitcom ou CCTV.
- `Filmes`: canais cuja grade e essencialmente filmes.
- `Séries`: canais de series, sitcoms e programacao seriada.
- `CCTV`: canais CCTV gratuitos/diretos mantidos separadamente, independentemente do genero do conteudo.
- `Beta`: endpoints experimentais usados para validar adaptacoes novas da bridge sem misturar o teste com a grade principal.

A interface mostra primeiro as categorias encontradas na playlist. Ao entrar em uma delas, mostra apenas seus canais; `Voltar` retorna primeiro para as categorias e depois para o menu Smart.

## Perfil aceito

- Extended M3U em UTF-8 (`.m3u8`).
- Uma entrada = `#EXTINF` + URL HTTP/HTTPS.
- `group-title` e obrigatorio.
- Preferir HLS H.264/AVC + AAC em MPEG-TS, ate 1080p/60 fps.
- URLs simples, sem token/query, continuam sendo o padrao.
- Headers externos especiais continuam proibidos na lista remota.
- Na grade estavel, nao usar Widevine, PlayReady, FairPlay, DASH-only, HEVC/H.265, AV1, VP9, AC-3/E-AC-3 ou HLS fMP4/CMAF (`#EXT-X-MAP`).

### Perfis da bridge

O atributo `x-profile` descreve uma excecao comprovada e serve para os validadores/documentacao; o parser remoto continua entregando nome, grupo e URL ao player.

- `bridge`: a bridge moderna e necessaria por redirects, query, TLS ou outra complexidade de transporte ja comprovada. MasterChef e CCTV-15 usam este perfil.
- `bridge-normalize`: a V7.3.4 reescreve o media playlist para um HLS v3 minimo, preservando temporizacao e `EXTINF`/segmentos e retirando bookkeeping proprietario que confunde o parser legado. Novelissima usa este perfil.
- `bridge-aes`: HLS AES-128 CBC com `KEYFORMAT=identity`. A V7.3.4 busca a chave/IV, descriptografa o segmento na bridge e entrega MPEG-TS em claro ao GStreamer antigo, que nao recebe `EXT-X-KEY`. Os dois Pluto Beta usam este perfil.

`bridge-aes` nao significa suporte a DRM moderno. Qualquer KEYFORMAT diferente de `identity`, ou Widevine/PlayReady/FairPlay, continua rejeitado.

## CCTV

A categoria CCTV foi preenchida a partir dos canais `x-source="Free-TV"` da `cn.m3u` quando havia URL HLS direta, mais o CCTV-15 que ja era controle conhecido do firmware. A bateria inicial aprovou CCTV-1, 2, 3, CCTV-4 Asia e Europa, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15 e 17.

Duas entradas foram deliberadamente deixadas fora da grade remota depois do teste real do workflow: CCTV-16 respondeu conteudo que nao era manifesto HLS; CCTV-4 America apresentou certificado TLS expirado no endpoint atual. Elas podem voltar se aparecer uma fonte direta que passe o mesmo gate.

## URL consumida pelo player

`https://raw.githubusercontent.com/HyakkimaruPY/Lista-M3U.m3u/main/old_hls.m3u8`

O navegador antigo nao acessa essa URL diretamente. A bridge Go faz o HTTPS, interpreta o M3U e entrega JSON local em `http://127.0.0.1:8765/c`.

## Bateria de testes

1. `scripts/validate_streams.py`: confirma audio e video com `ffprobe`/`ffmpeg`.
2. `scripts/validate_old_hls.py`: valida estrutura, grupos e os perfis de compatibilidade da bridge.
3. `scripts/probe_legacy_media.py`: inspeciona profundamente manifests/codecs/tags/chaves dos canais problemáticos.
4. `tests/test_old_hls.py`: impede regressao da grade, URLs e perfis.

Timeout, DNS, bloqueio regional ou indisponibilidade momentanea continuam sendo `uncertain`. Incompatibilidades reais da grade estavel falham o gate; a categoria Beta permanece isolada para validacao fisica das adaptacoes em desenvolvimento.
