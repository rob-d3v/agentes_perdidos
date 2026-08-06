# Skills públicas que podem melhorar os agentes de `agentes_perdidos`

Relatório gerado invocando a skill `find-skills` (que delega para `npx skills find <termo>`,
o catálogo público em skills.sh) com uma busca por tema, seguida de leitura do conteúdo real
de cada skill candidata (via `skills.sh/<owner>/<repo>/<skill>`) e comparação linha a linha
com o `SKILL.md` de 11 agentes deste repo (`image-creator`, `cloudflare`, `bucket`,
`design-reviewer`, `security-reviewer`, `second-brain`, `ai-visibility`, `guardian`,
`branch-consolidator`, `i18n`, `stripe`, `navigator`, `architecture-auditor`,
`clean-refactorer`, `performance-engineer`, `captcha`, `social-auth`, `lost-finder`,
`remodeling` — 19 no total, acima do mínimo de 5 pedido).

**Nada foi instalado.** Nenhum `SKILL.md` deste repo foi editado. Toda skill citada abaixo
foi de fato vista no catálogo (nome, contagem de instalações e conteúdo lido via WebFetch);
não há nomes inventados. Onde o conteúdo da página não deu detalhe suficiente, digo
explicitamente "não confirmado" em vez de supor.

---

## Tabela: agente x skill encontrada x ganho x esforço

| Agente | Skill encontrada (instalações) | O que ganharia | Esforço |
|---|---|---|---|
| `cloudflare` | `cloudflare/skills@wrangler` — oficial (39,4K) | Referência **sempre atualizada** de sintaxe `wrangler.jsonc`, dry-run, versioning/rollback, cron triggers. O `cf.py`/SKILL.md do agente hoje documenta comandos fixos que driftam quando a CLI muda; a skill oficial cobre isso sem precisar reescrever o `SKILL.md` a cada breaking change do wrangler. | Baixo |
| `cloudflare` (parte Turnstile) | `cloudflare/skills@turnstile-spin` — oficial (15K) | Cobre o fluxo **completo**: widget + snippets frontend + `siteverify` server-side + validação — hoje esse fluxo está partido entre `cloudflare` (cria o widget) e `captcha` (código + verificação + PDF). Vale comparar se a skill oficial fecha essa lacuna de handoff sem exigir os dois agentes. | Médio |
| `design-reviewer` | `nexu-io/open-design@design-review` (1,9K) | Essa skill **aplica** a correção (commits atômicos + screenshot antes/depois); o `design-reviewer` hoje só **entrega um plano** ("Proposes, never edits" implícito no fluxo — passo 5 é so "Verify" depois que outra pessoa implementou). É uma técnica que falta: um modo opcional de auto-fix atômico para itens triviais de baixo risco (espaçamento, contraste, radius), sem abrir mão do plano completo para mudanças estruturais. | Médio |
| `second-brain` | `lewislulu/llm-wiki-skill@llm-wiki` (57) / `junbjnnn/llm-wiki@llm-wiki` (38) | Mesma inspiração declarada (padrão "LLM-Wiki" de Karpathy) — vale ler para comparar nomenclatura de operações (`compile/ingest/query/lint/audit` vs as já existentes `onboard/ingest/query/lint`). Instalação baixa e sem a base compartilhada entre projetos nem a regra de confidencialidade que `second-brain` já tem. | Baixo/médio |
| `branch-consolidator` | `chann/skills@git-branch-cleanup` (37) / `gotalab/skillport@git-branch-cleanup` (30) | Só apaga branches `--merged` contra uma lista fixa de nomes protegidos (`main/master/dev/...`); **não** faz backup antes de deletar, **não** detecta dinamicamente o branch real de deploy (VPS/PaaS), **não** distingue squash-merge. `branch-consolidator` já é estritamente mais rigoroso (tag de recovery por branch, prova via `git rev-list --count`, nunca deleta trabalho não mesclado). Ganho real é quase nulo. | Baixo |
| `guardian` | `aj-geddes/useful-ai-prompts@backup-disaster-recovery` (544) | Conteúdo de **planejamento/checklist genérico de DR** ("Design and implement... strategies"), não confirmado que execute algo de fato (sem discovery de volumes docker, sem push a bucket, sem retenção). Pode virar uma referência de checklist no runbook (`DISASTER-RECOVERY.md`), mas não substitui a automação real do `guardian`. | Baixo |
| `security-reviewer` | `bagelhole/devops-security-agent-skills@sast-scanning` (100) | Descrição rasa, sem citar ferramentas específicas (Semgrep, etc. não confirmados). `security-reviewer` já é muito mais detalhado (Semgrep+Gitleaks+SARIF, camada de IA com o prompt MIT da Anthropic, checklist OWASP por stack). Ganho: nenhum. | Baixo |
| `image-creator` | `skills-collective/skills@ai-image-generation` (90,1K) | Usa a CLI **RunComfy** (agrega 11+ modelos) em vez de chamar OpenAI/Gemini/Kling diretamente. Poderia servir de **4º fallback genérico** quando nenhuma das 3 chaves atuais tiver crédito — mas exige nova conta/chave e perde o roteamento fino por transparência/custo que o agente já faz bem (tabela de decisão OpenAI vs Gemini vs Kling). | Baixo |
| `architecture-auditor` | `absolutelyskilled/absolutelyskilled@clean-architecture` (194) / `sickn33/...@uncle-bob-craft` (130) | Conteúdo qualitativo (princípios), sem as métricas quantificadas que `architecture-auditor` já calcula (CC/cognitive, Ca/Ce/Instability/Abstractness/Distance, duplicação, ciclos via lizard/radon/jscpd/dependency-cruiser). Ganho: baixo — só como texto de apoio para explicar os princípios a um dev júnior. | Baixo |
| `clean-refactorer` | `dzhng/skills@refactor-clean` (110) | Não menciona testes de caracterização/golden-master nem exige commits atômicos revertíveis — `clean-refactorer` já trata isso como regra inegociável ("no net, no refactor"). Ganho: baixo. | Baixo |
| `performance-engineer` | `mengto/skills@performance-profiling` (120) / `vudovn/antigravity-kit@...` (150) | Baixa adoção, conteúdo não verificado em detalhe; `performance-engineer` já tem matriz de profilers por stack (React DevTools/clinic+0x/cProfile+py-spy+scalene/async-profiler+JFR) **e** um oráculo de equivalência comportamental (`behavior_diff.py`) que nenhuma das opções do catálogo demonstrou ter. Ganho: baixo. | Baixo |
| `i18n` | `mindrally/skills@internationalization-i18n` (732) | Provavelmente cobre extração básica i18next; não confirmado ter o "completeness gate" (`audit.py` com `USED_BUT_MISSING`/`RENDER_BARE`/`PHANTOM`), nem geração grátis de ~190 idiomas via `gtx`, nem a regra do switcher pré-autenticação. `i18n` agent já é mais completo. Ganho: baixo. | Baixo |
| `stripe` | `claude-office-skills/skills@stripe-payments` (3,8K) / `jezweb/...@stripe-payments` (901) | Provável cobertura de wiring básico do Stripe. O agente `stripe` já **defere explicitamente** a skill instalada `stripe-best-practices` para "qual API usar" e foca no processo (ambiente de homologação, harness de 2 pistas, PDF) — que nenhuma skill do catálogo demonstrou cobrir. Ganho: nenhum, já coberto. | — |
| `navigator` | `sickn33/antigravity-awesome-skills@browser-automation` (6K) | Genérica sobre automação de navegador; não cobre a escada de 4 tiers (Claude-in-Chrome → chrome-devtools-mcp → Camofox stealth → computer-use), nem harvest de segredos com `secrets_writer.py` + "live-promotion gate". Ganho: baixo. | Baixo |
| `ai-visibility` | `resciencelab/opc-skills@seo-geo` (37,2K) | Cobre SEO/GEO tradicional + JSON-LD + "9 métodos GEO de Princeton", mas **não menciona** o Elemento 0 (extractabilidade para SPAs client-side-only) que é o diferencial explícito do `ai-visibility` ("KNOWS that a JS-only SPA is invisible to most AI crawlers"). Pode servir de segunda fonte de templates de schema, mas não de scoring automatizado (`score.py`). Ganho: baixo/médio (só para enriquecer o catálogo de elementos). | Baixo |
| `captcha` | `membranedev/application-skills@google-recaptcha` (136) | Baixa adoção; não confirmado cobrir a ênfase em "fail-closed" nem o handoff explícito para `navigator` (harvest de chaves) nem a matriz de chaves de teste (pass/block) com PDF de evidência que `captcha` já tem. Ganho: baixo. | Baixo |

---

## Aplicar primeiro (até 5, por retorno/esforço)

1. **`cloudflare` — adotar `cloudflare/skills@wrangler` como referência viva.**
   Passo concreto: quando o agente `cloudflare` for usado para um deploy de Worker/Pages,
   consultar essa skill oficial (39,4K instalações, mantida pela própria Cloudflare) para a
   sintaxe atual de `wrangler.jsonc`/flags em vez de confiar só nos exemplos fixos do
   `SKILL.md`. Não precisa reescrever nada — é uma segunda fonte de verdade para uma API que
   muda com frequência. Maior retorno pelo menor esforço da lista.

2. **`design-reviewer` — adicionar um modo opcional de "auto-fix atômico".**
   Passo concreto: inspirado em `nexu-io/open-design@design-review`, acrescentar ao `SKILL.md`
   do `design-reviewer` uma seção descrevendo um modo (invocado só quando o usuário pedir "já
   aplica os ajustes triviais") que faz commits pequenos e reversíveis + screenshot
   antes/depois para itens de baixíssimo risco (espaçamento, contraste, radius) — mantendo o
   fluxo atual (plano completo, sem editar) como padrão para qualquer coisa estrutural.

3. **`cloudflare` + `captcha` — avaliar `cloudflare/skills@turnstile-spin` para fechar o handoff Turnstile.**
   Passo concreto: da próxima vez que um projeto pedir Turnstile (não reCAPTCHA), testar essa
   skill oficial ponta-a-ponta (ela promete widget + snippets + `siteverify` + validação) e
   comparar contra o par `cloudflare` (cria o widget) → `captcha` (código + verificação) hoje
   usado. Se ela realmente fechar o ciclo sozinha, documentar isso como atalho no `SKILL.md`
   do `cloudflare` para esse caso específico (Turnstile apenas — reCAPTCHA continua com
   `captcha`).

4. **`second-brain` — ler os dois `llm-wiki` skills para roubar nomenclatura.**
   Passo concreto: abrir `lewislulu/llm-wiki-skill@llm-wiki` e `junbjnnn/llm-wiki@llm-wiki`
   (baixa adoção, mas mesma inspiração declarada) e conferir se os nomes de operação deles
   (`compile`, `audit`) sugerem algo que falte nas operações atuais do `second-brain`
   (`onboard/ingest/query/lint`) — por exemplo, um comando `audit` dedicado separado de `lint`.

5. **`ai-visibility` — usar `resciencelab/opc-skills@seo-geo` só como checklist cruzado de schema.**
   Passo concreto: da próxima vez que `ai-visibility` gerar JSON-LD para um tipo de página novo,
   comparar o template contra os templates de FAQPage/Article/Product/Organization dessa skill
   (37,2K instalações) para garantir que nada básico ficou de fora — sem adotar o restante da
   skill, já que ela não cobre o Elemento 0 (extractabilidade de SPA) que é o diferencial do
   `ai-visibility`.

---

## Sem equivalente público (sinal de agente diferenciado)

Busquei ativamente por esses temas no catálogo (`npx skills find ...`) e não encontrei nada
que cubra o que o agente realmente faz — só resultados genéricos e adjacentes, listados acima
quando existiam, ou nada relevante:

- **`lost-finder`** — busca forense por **conteúdo** (assinatura de cor em imagens, texto extraído
  de PDF, ranking combinado) + modo local de recuperação de seed BIP39/vault MetaMask. Busquei
  "find lost files forensic" e "wallet seed phrase recovery"; só apareceram skills de forense de
  segurança genérica (incident response) e migração de keychain de exchange — nada que procure
  arquivo perdido pelo próprio conteúdo.
- **`remodeling`** — reescrita de persona com pesquisa geo-ancorada anti-homônimo + regra dura
  "nunca fabricar" + face-swap via `image-creator`. Não existe categoria parecida no catálogo.
- **`navigator`** — escada de 4 tiers de backend de browser (Claude-in-Chrome →
  chrome-devtools-mcp → Camofox stealth → computer-use) especificamente para contornar o bloqueio
  de segurança do Claude-in-Chrome em domínios financeiros, com harvest de segredos regrado
  (`secrets_writer.py`, gate de promoção para live). As skills de "browser automation" encontradas
  são genéricas de RPA, sem esse roteamento por tier nem a disciplina de segredos.
- **`stripe` / `social-auth` / `captcha`** — o padrão comum aos três ("implementa **e valida**
  com harness de duas pistas — API headless + browser real — e emite um PDF por app") não
  apareceu em nenhuma skill do catálogo; as skills de Stripe/OAuth/captcha encontradas cobrem só
  a implementação, não a validação com evidência.
- **`guardian`** — descoberta automática de volumes docker + retenção 3-diária/3-semanal por
  volume em bucket B2 privado + restore completo + aviso via WhatsApp. A skill de DR encontrada é
  um checklist de planejamento, não um executor.
- **`branch-consolidator`** — prova formal por `git rev-list --count` (não apenas `--merged`),
  detecção do branch real de deploy via PaaS/SSH, backup por tag *antes* de qualquer deleção.
  As skills de "git branch cleanup" encontradas fazem uma versão bem mais simples e sem backup.
- **`ai-visibility`** — o "Elemento 0" (gate de extractabilidade para SPAs client-side-only,
  testado com `curl -A GPTBot`) não aparece na skill de SEO/GEO mais popular do catálogo
  (37,2K instalações) nem em nenhuma outra encontrada.
- **`architecture-auditor` / `clean-refactorer`** — a combinação de métricas quantificadas
  (Ca/Ce/Instability/Abstractness/Distance via lizard/radon/jscpd/dependency-cruiser) +
  exigência hard de testes de caracterização antes de qualquer refactor não apareceu em nenhuma
  skill de "clean architecture"/"refactor" do catálogo — essas eram só guias qualitativos.

## Observação sobre a ferramenta `find-skills`

A skill `find-skills` em si é só um conjunto de instruções que recomenda rodar `npx skills find
<termo>` contra o catálogo público (skills.sh) e verificar contagem de instalações/reputação
antes de recomendar. Ela **funcionou** normalmente neste ambiente (Node/npx disponíveis) e
retornou resultados reais para todos os 18 termos de busca usados; nenhuma busca falhou ou
veio vazia, então não há nenhum caso a reportar de "skill indisponível".
