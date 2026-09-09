# Independent extraction and cross-check

Read only when the user or runner explicitly enables subagents.

The main agent coordinates this workflow. Subagents perform only their assigned extraction; they must not spawn further subagents or write the final output files.

Respect user-specified subagent models. When model selection is supported and the user has not specified a model, prefer an available lower-cost model capable of full-document extraction, including the required context length, image understanding, and tool use. Apply the choice through actual tool parameters or agent configuration, not merely the task description. If model selection is unavailable, use the inherited model without claiming a different model was used.

1. **Independent drafts.** Start two subagents, each tasked with extracting the entire supplied document. Give both the source path, this skill, the schema paths, and separate temporary output locations. Each must read the full skill, all schema files, and the document. Neither may see the other draft or previous extraction results before submitting its own draft.
2. **Source support.** Each subagent returns candidate rows and exceptions, with supporting passages and source locations for populated values and relationships, including page, table, figure, or panel identifiers where available. Keep review material separately from the candidate JSONL; do not add fields to the schema.
3. **Compare.** After both drafts are complete, the main agent aligns records by source-supported entity identity, experimental group, and measurement conditions, not row order or generated UUIDs. Compare values, attribution, missing records, and cases where only one draft supplies a value.
4. **Resolve from the source.** Re-read the relevant text, tables, or images to resolve differences. Another agent's answer, agreement, or majority vote is not evidence. Also spot-check agreeing results against the source, especially numerical values and entity relationships. Apply the existing missing-information and conflicting-evidence rules when the source remains ambiguous or contradictory; a disagreement between drafts alone is not a conflict in the source.
5. **Final output.** Only the main agent writes the final JSONL and exception sidecar. Reconcile identifiers and references across accepted records, and log exceptions according to the final decisions rather than copying both draft logs. Follow the existing output format and completion checks.

If subagents are unavailable or two independent drafts cannot be completed, finish using the single-agent workflow and disclose the limitation in the final response. State whether the cross-check was completed; do not claim it occurred when it did not. Keep this execution status out of the extracted rows and source-exception sidecar.

