import { useEffect, useState } from "react"
import type { ConsoleClient, PersonaPack } from "@/features/shell/model"

export function PackArtwork({
  pack,
  client,
}: {
  pack: PersonaPack
  client: ConsoleClient
}) {
  const [image, setImage] = useState<{ key: string; url: string } | null>(null)
  const key = pack.artworkRef
  useEffect(() => {
    let active = true
    if (key)
      void client
        .packArtwork(pack.reference)
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
  }, [client, key, pack.reference])
  return key && image?.key === key ? (
    <img
      src={image.url}
      alt={`${pack.name}的封面`}
      loading="lazy"
      onError={() => setImage(null)}
    />
  ) : (
    <span aria-hidden="true">{pack.name.slice(0, 1)}</span>
  )
}
