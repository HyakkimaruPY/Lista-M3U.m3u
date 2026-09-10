# Old HLS

`old_hls.m3u8` e a grade remota do player legado da TV Philco. A TV baixa esta lista do GitHub ao abrir a area de TV, entao trocar, remover ou adicionar um canal nao exige gerar um novo `.bin`.

## Categorias

A partir da V7.3.2 DYNCAT, as categorias deixam de ser fixas no firmware: a interface descobre automaticamente os valores distintos de `group-title` presentes na playlist. Portanto, criar ou remover uma categoria passa a ser somente uma alteracao no M3U.

Grupos atuais:

- `Variedade`: novelas, culinaria, humor, canais gerais e tudo que nao seja exclusivamente filme, serie/sitcom ou CCTV.
- `Filmes`: canais cuja grade e essencialmente filmes.
- `Séries`: canais de series, sitcoms e programacao seriada.
- `CCTV`: canais CCTV gratuitos/diretos mantidos separadamente, independentemente do genero do conteudo.
- `Beta`: endpoints experimentais que ainda precisam de validacao fisica na TV. Falhas desta categoria sao reportadas pelo gate, mas nao derrubam a lista estavel.

A interface mostra primeiro as categorias encontradas na playlist. Ao entrar em uma delas, mostra apenas seus canais; `Voltar` retorna primeiro para as categorias e depois para o menu Smart.

## Perfil aceito

- Extended M3U em UTF-8 (`.m3u8`).
- Uma entrada = `#EXTINF` + URL HTTP/HTTPS.
- `group-title` e obrigatorio.
- Preferir HLS H.264/AVC + AAC em MPEG-TS, ate 1080p/60 fps.
- URLs simples, sem token/query, continuam sendo o padrao.
- Uma fonte complexa suportada pela bridge pode ser marcada explicitamente com `x-profile="bridge"`.
- Headers externos especiais continuam proibidos na lista remota.
- Na grade estavel, nao usar DRM, Widevine, PlayReady, FairPlay, DASH-only, HEVC/H.265, AV1, VP9, AC-3/E-AC-3 ou HLS fMP4/CMAF (`#EXT-X-MAP`).
- A categoria Beta pode conter temporariamente fontes mais complexas para teste; o validador as classifica como experimentais/inconclusivas em vez de comprometer o gate da grade estavel.

## CCTV

A categoria CCTV foi preenchida a partir dos canais `x-source="Free-TV"` da `cn.m3u` quando havia URL HLS direta, mais o CCTV-15 que ja era controle conhecido do firmware. A bateria inicial aprovou CCTV-1, 2, 3, CCTV-4 Asia e Europa, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15 e 17.

Duas entradas foram deliberadamente deixadas fora da grade remota depois do teste real do workflow: CCTV-16 respondeu conteudo que nao era manifesto HLS; CCTV-4 America apresentou certificado TLS expirado no endpoint atual. Elas podem voltar se aparecer uma fonte direta que passe o mesmo gate.

## URL consumida pelo player

`https://raw.githubusercontent.com/HyakkimaruPY/Lista-M3U.m3u/main/old_hls.m3u8`

O navegador antigo nao acessa essa URL diretamente. A bridge Go faz o HTTPS, interpreta o M3U e entrega JSON local em `http://127.0.0.1:8765/c`.

## Bateria de testes

1. `scripts/validate_streams.py`: confirma audio e video com `ffprobe`/`ffmpeg`.
2. `scripts/validate_old_hls.py`: valida estrutura, grupos e perfil de compatibilidade legado.
3. `tests/test_old_hls.py`: impede regressao da grade e das regras de URLs.

Timeout, DNS, bloqueio regional ou indisponibilidade momentanea continuam sendo `uncertain`. Incompatibilidades da grade estavel falham o gate; entradas `Beta` sao mantidas como experimentais para teste fisico sem quebrar o conjunto estavel.
