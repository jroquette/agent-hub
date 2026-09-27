# AGENTS.md — agent-hub

Plataforma para criar, operar e observar hubs de agentes de IA para N projetos.
A spec está em `docs/SPEC.md`: leia antes de qualquer tarefa. As direções já definidas estão na seção "Direções definidas".

## Estado

Fase 0 (fundação). Ainda não há código: stack, comandos e definition of done entram aqui junto com o esqueleto.
Stack prevista: Python (FastAPI + Pydantic) no backend, React no frontend, SQLite como armazém na v1.

## Regras

1. **Autoria é do usuário.** Commits e PRs são de José Henrique Roquette (`roquettejh@gmail.com`).
   Nunca adicionar `Co-Authored-By` de IA, "Generated with", 🤖 ou qualquer indicação de que o trabalho foi feito por um agente,
   em commit, PR, comentário ou nome de branch.
2. **Branches:** `roquettejh/<desc>`, nunca `claude/…`. Nada de push em `main` nem force-push: toda mudança entra por PR.
3. **Spec primeiro.** Mudança de escopo ou de arquitetura atualiza `docs/SPEC.md` no mesmo PR.
4. **Sem segredos no repo.** Nada de tokens, chaves ou transcripts reais em código, testes ou fixtures.
5. **Repo privado.** O funcionamento interno (brain, workflows, regras) não é compartilhado fora do repo.

## Gotchas

- `cmd | tail` esconde o exit code. Redirecione para um arquivo e cheque `$?` antes de dizer que a suíte passou.
