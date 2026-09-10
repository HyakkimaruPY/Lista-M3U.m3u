# Playlists IPTV

- `cn.m3u`: canais chineses organizados por conteúdo. A origem permanece em `x-source`; Free-TV tem prioridade nas substituições, seguida de IPTV-org. BurningC4 pode fornecer logos históricas, mas não streams.
- `srhell02iptv.m3u`: seleção principal. Pluto usa categorias em português com sufixo `S` para os EUA e `BR` para o Brasil. Episódios VOD ficam separados dos canais ao vivo.
- `old_hls.m3u8`: grade remota do player legado Philco. A compatibilidade deixou de ser limitada a HLS “simples”: o AUTOHLS detecta pelo manifesto/segmentos quando deve usar proxy simples, normalização HLS v3, AES-128 CBC ou as duas adaptações. Não há tag técnica obrigatória no M3U. Regras completas em `OLD_HLS_README.md`.

URLs alternativas distintas são preservadas, mesmo quando o nome ou ID EPG coincide. A curadoria remove apenas solicitações de reprodução exatamente repetidas, considerando URL, cabeçalhos e diretivas. Não troca URLs por listas fixas antigas. Rede-Super permanece; Rede-Gospel/Renascer não são reinseridas.

## Curadoria e testes locais

```sh
python3 scripts/curate_main_playlist.py
python3 scripts/curate_main_playlist.py --check
python3 -m unittest discover -s tests -v
python3 scripts/validate_streams.py --playlist cn.m3u --workers 6 --retries 2 --timeout 25 --decode-seconds 4
python3 scripts/validate_old_hls.py --playlist old_hls.m3u8 --strict
```

FFmpeg, ffprobe e OpenSSL são necessários para a bateria completa do `old_hls.m3u8`. OpenSSL é usado para reproduzir no CI a descriptografia AES-128-CBC que a bridge faz na TV. A inspeção visual Pluto da playlist principal também pode usar Tesseract com inglês. Os testes unitários do classificador AUTOHLS não precisam de rede.

## Significado dos resultados

- `healthy`: áudio e vídeo foram detectados, decodificados e produziram dados durante pelo menos 80% da amostra pedida. Com OCR habilitado, não foi reconhecida uma tela de indisponibilidade conhecida.
- `compatible` no gate Old HLS: o HLS observado cabe em um perfil implementado no player (`simple`, `normalize`, `aes128` ou `normalize+aes128`) e a transformação necessária passou.
- `incompatible` no gate Old HLS: foi observado um recurso ainda não suportado ou uma transformação comprovadamente inválida. Em modo `--strict`, bloqueia o CI.
- `remove`: falha definitiva repetida em pelo menos duas tentativas nos validadores que possuem modo de manutenção. A execução normal apenas relata; `--apply` permite remoções onde isso é explicitamente suportado.
- `uncertain`: timeout, autorização, bloqueio regional, ausência de áudio/vídeo, decodificação insuficiente ou erro transitório. O canal permanece para evitar remoção por falha do runner.
- `skipped`: entrada fora do filtro ou do limite solicitado.

Um resultado saudável é uma amostra de reprodução no local e horário do teste; não garante disponibilidade contínua nem identidade da programação. Um processo FFmpeg com código zero, sozinho, não comprova reprodução.

Os relatórios não incluem URLs completas quando o script correspondente protege parâmetros sensíveis. Reparos por número de linha exigem que o SHA-256 da playlist coincida com o relatório. Se o arquivo mudar, valide novamente.

## Workflows

- **Estrutura e regressões IPTV**: valida sintaxe e invariantes em pushes e PRs, incluindo `.m3u8`, sem depender de rede de streaming.
- **Validar Old HLS**: roda diariamente e em mudanças de `old_hls.m3u8`. Primeiro executa os testes do classificador AUTOHLS; depois abre o HLS real, escolhe a variante compatível, simula a mesma normalização/AES da TV e só então roda `ffprobe`/`ffmpeg`. Query strings e redirects deixam de ser rejeitados por regra quando o caminho real passa. CMAF/fMP4, SAMPLE-AES, KEYFORMAT não-identity e formatos ainda não implementados continuam bloqueados.
- **Validar e manter streams IPTV**: audita PRs sem escrever neles. A manutenção diária pode reparar/remover Pluto da principal e reparar a lista chinesa. Demais canais da principal não são modificados automaticamente. As outras listas são auditadas sem alterações.
- **Validar canais principais não-Pluto**: auditoria apenas; não remove canais nem faz commits em PRs.
- **Sincronizar China com principal**: execução manual na main, simulação por padrão. Para aplicar, marque `apply_changes`. Só usa candidatos que passam na validação; preserva cabeçalhos necessários e distingue CCTV-4K/8K de CCTV-4/8.

As rotinas que escrevem na main compartilham um grupo de concorrência, e o push normal recusa sobrescrever mudanças concorrentes. A simulação de sincronização trabalha em cópias temporárias.

## Old HLS / AUTOHLS

A grade `old_hls.m3u8` deve continuar simples editorialmente: `#EXTINF`, `group-title` e URL. O tratamento técnico não é declarado manualmente. `scripts/hls_compat.py` analisa o HLS e espelha a lógica da bridge do firmware.

Hoje o player sabe adaptar automaticamente:

- MPEG-TS claro clássico;
- manifests com `EXT-X-DISCONTINUITY-SEQUENCE`, `EXT-X-MEDIA-SEGMENT-*`, CUE/SCTE e bookkeeping que precisa ser retirado para o parser GStreamer antigo;
- HLS AES-128 CBC com `KEYFORMAT=identity`, entregando TS já descriptografado ao decoder;
- combinação de normalização + AES-128.

Para ampliar esse conjunto no futuro, a regra é adicionar primeiro o tratamento ao player **e** um teste equivalente ao `hls_compat.py`; somente depois o CI passa a considerar o novo perfil admissível. Isso evita regressões e evita descartar streams que o player já consegue adaptar.

## Revisão de 6 de setembro de 2026

Curadoria preservou todas as 372 entradas chinesas e 257 da principal, incluindo URLs e cabeçalhos. A principal passou de 41 para 33 grupos; a chinesa passou de dois grupos por fornecedor para 11 grupos por conteúdo. Não havia solicitações de reprodução exatamente duplicadas para excluir.

Verificação: 13 testes de regressão aprovados, quatro workflows com YAML válido, estrutura M3U verificada e stream HTTP local com áudio/vídeo decodificado por quatro segundos. Na tentativa de auditoria externa, 193 resultados chineses e 115 da principal foram registrados como inconclusivos por timeout. A auditoria foi interrompida, sem remoções e sem comprovar disponibilidade externa. Não houve conclusão de OCR externo nessa execução. Os workflows conservam a auditoria no ambiente GitHub Actions.

### Tela persistente com o logo Pluto

A inspeção visual usa cinco quadros ao longo de 30 segundos. Um logo grande e central, identificado por OCR ou pela composição amarela sobre fundo escuro, em pelo menos quatro quadros com cobertura de 24 segundos resulta em `uncertain`. A heurística não prova um loop infinito e não remove canais; ela impede atestar programação quando somente a vinheta foi observada. Logos pequenos de canto e vinhetas breves não satisfazem esse critério.

A captura enviada da Nickelodeon Clássico foi reconhecida pela heurística de cores; o OCR isolado não reconheceu o logo estilizado. O ID 6824ce10c5d53e1351ceb8d1 coincide com a grade BR consultada em 6/9/2026. O link foi preservado, pois não foi possível comprovar outro stream reproduzindo programação nesta sessão.
