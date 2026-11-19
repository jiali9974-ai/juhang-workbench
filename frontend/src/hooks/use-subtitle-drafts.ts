import { useEffect, useState } from "react"
import { api, type OutputVideo } from "@/lib/api"
import { outputKey, subtitleChanges, type SubtitleDraft } from "@/lib/frame-workflow"
import { useSessionState } from "@/hooks/use-session-state"

export function useSubtitleDrafts(source: Pick<OutputVideo, "batch" | "id"> | null, revision: string) {
  const [drafts, setDrafts] = useSessionState<Record<string, SubtitleDraft>>("frame-editor.subtitle-drafts", {})
  const [result, setResult] = useState<{ request: string; error: string } | null>(null)
  const [refresh, setRefresh] = useState(0)
  const batch = source?.batch, id = source?.id, key = source ? outputKey(source) : ""
  const request = JSON.stringify([key, revision, refresh])
  useEffect(() => {
    if (!batch || !id) return
    let live = true
    api.scripts(batch).then((scripts) => {
      if (!live) return
      const script = scripts.find((item) => item.id === id)
      if (!script) throw new Error("这条成片没有对应的剪辑脚本，无法修改字幕")
      setDrafts((previous) => previous[key] && subtitleChanges(previous[key]).length ? previous : {
        ...previous, [key]: { script, saved: script.lines.map((line) => line.subtitle) },
      })
      setResult({ request, error: "" })
    }).catch((failure) => { if (live) setResult({ request, error: String(failure).replace(/^Error: /, "") }) })
    return () => { live = false }
  }, [batch, id, key, request, setDrafts])
  const reload = () => {
    if (drafts[key] && subtitleChanges(drafts[key]).length && !window.confirm("重新载入会放弃这条成片尚未保存的字幕修改，继续？")) return
    setDrafts((previous) => { const next = { ...previous }; delete next[key]; return next })
    setRefresh((value) => value + 1)
  }
  const update = (index: number, subtitle: string) => setDrafts((previous) => {
    const draft = previous[key]
    return !draft ? previous : { ...previous, [key]: { ...draft, script: { ...draft.script,
      lines: draft.script.lines.map((line, i) => i === index ? { ...line, subtitle } : line),
    } } }
  })
  async function saveAll() {
    for (const [savedKey, sent] of Object.entries(drafts)) {
      const changes = subtitleChanges(sent)
      if (!changes.length) continue
      const { script } = await api.saveSubtitles(sent.script.batch, sent.script.id, changes)
      setDrafts((previous) => {
        const current = previous[savedKey]
        if (!current) return previous
        return { ...previous, [savedKey]: { saved: script.lines.map((line) => line.subtitle), script: { ...script,
          duration: current.script.duration, has_output: current.script.has_output,
          lines: script.lines.map((line, index) => {
            const local = current.script.lines[index], original = sent.script.lines[index]
            return local && original && local.clip === line.clip && local.start === line.start && local.end === line.end && local.subtitle !== original.subtitle
              ? { ...line, subtitle: local.subtitle } : line
          }),
        } } }
      })
    }
  }
  return { draft: key ? drafts[key] : undefined, loading: !!source && result?.request !== request && !drafts[key], error: source && result?.request === request ? result.error : "", update, reload, saveAll,
    dirty: Object.values(drafts).some((draft) => subtitleChanges(draft).length > 0) }
}
