import { useCallback, useRef, useState } from "react"
import { Plus } from "lucide-react"
import { Button } from "@/ui"
import type { ArtifactDetail, RuntimeStatus } from "@/features/control/model"
import type { ConsoleClient, PersonaPack } from "@/features/shell/model"
import { useResource } from "@/features/shell/use-resource"
import { PageIntro } from "@/features/shell/page-parts"
import { personaBlueprint } from "../model"
import { copyPack, newPack, nextVersion, type PackDraft } from "../authoring"
import { downloadPack, MAX_PACK_BYTES, parsePackFile } from "../pack-file"
import { newPackId } from "../pack-id"
import { usePackPreview } from "../use-pack-preview"
import { PackCatalog } from "./pack-catalog"
import { PackEditor } from "./pack-editor"
import { PackPreview } from "./pack-preview"

export function StorePage({
  client,
  status,
  onSaved,
  readPersona,
}: {
  client: ConsoleClient
  status: RuntimeStatus | null
  onSaved: () => Promise<void>
  readPersona: (id: string) => Promise<ArtifactDetail>
}) {
  const [collection, setCollection] = useState<"official" | "mine">("official")
  const [offset, setOffset] = useState(0)
  const [draft, setDraft] = useState<PackDraft | null>(null)
  const [editorKey, setEditorKey] = useState(0)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  const acting = useRef(false)
  const read = useCallback(
    () => client.packs(collection, offset),
    [client, collection, offset]
  )
  const vm = useResource(read)
  const preview = usePackPreview(client, status, readPersona)
  const blocked = !status?.ready || !!status.activeTask
  const openEditor = (value: PackDraft) => {
    preview.close()
    setDraft(value)
    setEditorKey((key) => key + 1)
    setNotice("")
    setError("")
  }
  const saved = async () => {
    await Promise.all([vm.reload(), onSaved()])
    setNotice("人格包已保存。可打开预览，核对后应用。")
  }
  const action = async (operation: () => Promise<unknown>, message: string) => {
    if (acting.current) return
    acting.current = true
    setBusy(true)
    setError("")
    try {
      await operation()
      preview.close()
      await Promise.all([vm.reload(), onSaved()])
      setNotice(message)
    } catch (e) {
      const message = e instanceof Error ? e.message : "操作失败，请重新核对"
      setError(message)
      preview.failed(message)
      await onSaved()
    } finally {
      acting.current = false
      setBusy(false)
    }
  }
  const edit = async (pack: PersonaPack) => {
    if (acting.current) return
    acting.current = true
    setBusy(true)
    try {
      const target = await client.packLookup(pack.reference)
      if (!target.pack) throw new Error("人格包已移除，请刷新列表")
      const personal = pack.reference.startsWith("mine/")
      openEditor({
        pack: personal
          ? {
              ...target.pack,
              seed: {
                ...target.pack.seed,
                version: nextVersion(target.pack.seed.version),
              },
            }
          : copyPack(target.pack),
        ...(personal ? { target } : {}),
        title: personal ? "编辑已保存包" : "复制到我的包",
      })
      setCollection("mine")
      setOffset(0)
    } catch (e) {
      setError(e instanceof Error ? e.message : "读取失败")
    } finally {
      acting.current = false
      setBusy(false)
    }
  }
  const importFile = async (file: File | undefined) => {
    if (!file || acting.current) return
    acting.current = true
    setBusy(true)
    setError("")
    try {
      if (file.size > MAX_PACK_BYTES) throw new Error("人格包不能超过 3 MiB")
      openEditor({
        pack: parsePackFile(await file.text()),
        title: "导入并编辑人格包",
      })
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "文件格式无效；请检查不支持的字段及内容"
      )
    } finally {
      acting.current = false
      setBusy(false)
    }
  }
  return (
    <div className="console-page console-store">
      <PageIntro title="人格小铺" />
      <div className="store-tabs">
        {(["official", "mine"] as const).map((value) => (
          <Button
            key={value}
            disabled={busy}
            variant={collection === value ? "default" : "ghost"}
            onClick={() => {
              setCollection(value)
              setOffset(0)
            }}
          >
            {value === "official" ? "官方种子" : "我的包"}
          </Button>
        ))}
      </div>
      {collection === "mine" && (
        <section className="console-panel mb-6 space-y-4 p-5">
          <div className="flex flex-wrap gap-3">
            <Button
              disabled={busy || blocked}
              onClick={() =>
                openEditor({ pack: newPack(), title: "创建个人包" })
              }
            >
              <Plus size={15} />
              创建个人包
            </Button>
            <label className="console-upload">
              导入人格包 / JSON
              <input
                type="file"
                accept=".json,application/json"
                disabled={busy || blocked}
                onChange={(e) => {
                  void importFile(e.target.files?.[0])
                  e.target.value = ""
                }}
              />
            </label>
            <Button
              variant="outline"
              disabled={busy || blocked || !status?.persona}
              onClick={() => {
                const persona = status?.persona
                if (!persona) return
                void action(async () => {
                  const detail = await readPersona(persona.id)
                  openEditor({
                    pack: {
                      ...newPack(),
                      seed: personaBlueprint(
                        detail,
                        typeof detail.artifact.payload["persona_name"] ===
                          "string"
                          ? detail.artifact.payload["persona_name"]
                          : "我的人格",
                        newPackId()
                      ),
                    },
                    title: "保存当前人格为包",
                  })
                }, "请核对包内容后保存。")
              }}
            >
              保存当前人格为包
            </Button>
          </div>
          <p className="text-sm text-muted-foreground">
            支持旧 seed JSON 和完整 v1
            包。保存蓝图不包含聊天、来源证据或私人记录；分享前请检查人格文字。
          </p>
        </section>
      )}
      {draft && (
        <PackEditor
          key={editorKey}
          initial={draft}
          client={client}
          blocked={blocked}
          onSaved={saved}
          onCancel={() => setDraft(null)}
        />
      )}
      {error && (
        <p role="alert" className="my-4 text-sm text-destructive">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="my-4 text-sm text-success">
          {notice}
        </p>
      )}
      <PackCatalog
        key={collection}
        client={client}
        data={vm.data}
        loading={vm.loading}
        error={vm.error}
        onRetry={vm.reload}
        status={status}
        busy={busy}
        offset={offset}
        onOffset={setOffset}
        onPreview={(pack) => {
          void preview.preview(pack)
        }}
      />
      <PackPreview
        key={preview.selected?.reference ?? "none"}
        client={client}
        selected={preview.selected}
        seed={preview.seed}
        current={preview.current}
        licenseText={preview.licenseText}
        error={preview.error}
        busy={busy}
        blocked={blocked}
        confirmed={preview.confirmed}
        setConfirmed={preview.setConfirmed}
        reviewRequired={preview.reviewRequired}
        onClose={preview.close}
        onReload={() => {
          if (preview.selected) void preview.preview(preview.selected)
        }}
        onEdit={() => {
          if (preview.selected) void edit(preview.selected)
        }}
        onExport={() => {
          if (preview.selected) {
            const ref = preview.selected.reference
            void action(
              async () =>
                downloadPack(
                  await client.packExport(ref),
                  `${ref.split("/")[1]}.seekmemory.json`
                ),
              "完整包已导出。"
            )
          }
        }}
        onRemove={() => {
          if (preview.selected) {
            const reference = preview.selected.reference
            void action(
              () =>
                client.persona({
                  operation: "remove",
                  reference,
                  confirmed: true,
                }),
              "已移入回收目录，当前人格内容保留。"
            )
          }
        }}
        onInstall={() => {
          if (
            preview.selected &&
            preview.seed &&
            preview.confirmed &&
            !preview.reviewRequired
          ) {
            const reference = preview.selected.reference,
              header = preview.current?.artifact.header
            void action(
              () =>
                client.persona({
                  operation: "install",
                  reference,
                  expectedId: header?.id ?? null,
                  expectedRevision: header?.revision ?? 0,
                  expectedDigest: preview.digest,
                  confirmed: true,
                }),
              "已应用人格包，并保留历史。"
            )
          }
        }}
      />
    </div>
  )
}
