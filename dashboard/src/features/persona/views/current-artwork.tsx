import { useEffect, useState } from "react"
import type { RuntimeStatus } from "@/features/control/model"
import type { ConsoleClient } from "@/features/shell/model"

export function CurrentArtwork({
  client,
  persona,
  className = "",
}: {
  client: ConsoleClient | undefined
  persona: RuntimeStatus["persona"]
  className?: string
}) {
  const application = persona?.packApplication
  const key = `${persona?.id}/${application?.reference}/${application?.artworkDigest}`
  const [image, setImage] = useState<{ key: string; url: string } | null>(null)
  useEffect(() => {
    let active = true
    if (client && application?.artworkDigest)
      void client
        .packArtwork(application.reference, application.artworkDigest)
        .then((art) => {
          if (active)
            setImage({ key, url: `data:image/png;base64,${art.dataBase64}` })
        })
        .catch(() => {
          if (active) setImage(null)
        })
    return () => {
      active = false
    }
  }, [client, persona, application, key])
  return image?.key === key ? (
    <img
      className={className}
      src={image.url}
      alt={`${persona?.name || "当前人格"}的封面`}
      onError={() => setImage(null)}
    />
  ) : (
    <div
      className={`${className} persona-artwork-fallback`}
      role="img"
      aria-label="当前人格暂无可用封面"
    >
      <span aria-hidden="true">◇</span>
    </div>
  )
}
