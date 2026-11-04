import type { PersonaSettings } from "../settings"

export function SettingsComparison({
  before,
  after,
}: {
  before: PersonaSettings | null
  after: PersonaSettings
}) {
  return (
    <section className="space-y-4" aria-label="应用前设定对照">
      <h3 className="font-semibold">当前与将应用的设定</h3>
      {!before && <p>当前还没有人格，将创建第一版。</p>}
      <div className="grid min-w-0 gap-4 sm:grid-cols-2">
        {(
          [
            ["当前设定", before],
            ["将应用的设定", after],
          ] as const
        ).map(([title, value]) => (
          <section
            key={title}
            className="min-w-0 space-y-4 rounded-xl border p-4"
            aria-label={title}
          >
            <h4 className="font-semibold">{title}</h4>
            <p className="wrap-anywhere">姓名：{value?.name || "未设置"}</p>
            <div>
              <h5 className="text-sm text-muted-foreground">人格正文</h5>
              <p className="wrap-anywhere whitespace-pre-wrap">
                {value?.persona || "无"}
              </p>
            </div>
            <div>
              <h5 className="text-sm text-muted-foreground">表达风格</h5>
              {Object.entries(value?.style ?? {}).length ? (
                <dl className="space-y-2">
                  {Object.entries(value?.style ?? {}).map(([key, item]) => (
                    <div key={key}>
                      <dt className="text-sm wrap-anywhere">{key}</dt>
                      <dd className="wrap-anywhere whitespace-pre-wrap">
                        {typeof item === "string" ? item : JSON.stringify(item)}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p>无</p>
              )}
            </div>
            <div>
              <h5 className="text-sm text-muted-foreground">相处边界</h5>
              {value?.boundaries.length ? (
                <ul className="list-disc space-y-1 pl-4">
                  {value.boundaries.map((item, index) => (
                    <li className="wrap-anywhere" key={index}>
                      {item}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>无</p>
              )}
            </div>
          </section>
        ))}
      </div>
    </section>
  )
}
