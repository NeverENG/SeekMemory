import { useEffect, useRef, useState } from "react"
import { settingsFromDetail } from "../persona/settings"
import type { ArtifactDetail, RuntimeStatus } from "../control/model"
import type { ConsoleClient, PersonaPack, PersonaSeed } from "../shell/model"

export function usePackPreview(
  client: ConsoleClient,
  status: RuntimeStatus | null,
  readPersona: (id: string) => Promise<ArtifactDetail>
) {
  const [selected, setSelected] = useState<PersonaPack | null>(null)
  const [seed, setSeed] = useState<PersonaSeed | null>(null)
  const [current, setCurrent] = useState<ArtifactDetail | null>(null)
  const [digest, setDigest] = useState("")
  const [licenseText, setLicenseText] = useState("")
  const [error, setError] = useState("")
  const [confirmed, setConfirmed] = useState(false)
  const [reviewRequired, setReviewRequired] = useState(false)
  const request = useRef(0)
  useEffect(
    () => () => {
      request.current++
    },
    []
  )
  const preview = async (pack: PersonaPack) => {
    const generation = ++request.current
    setSelected(pack)
    setSeed(null)
    setCurrent(null)
    setDigest("")
    setError("")
    setConfirmed(false)
    setReviewRequired(false)
    try {
      const [detail, persona] = await Promise.all([
        client.pack(pack.reference),
        status?.persona
          ? readPersona(status.persona.id)
          : Promise.resolve(null),
      ])
      if (generation !== request.current) return
      if (
        persona &&
        (persona.artifact.header.family !== "persona" ||
          persona.artifact.header.state !== "active")
      )
        throw new Error("当前人格已变化，请刷新后重新核对")
      if (persona) settingsFromDetail(persona)
      setSeed(detail.seed)
      setDigest(detail.digest)
      setLicenseText(detail.licenseText ?? "")
      setCurrent(persona)
    } catch (e) {
      if (generation === request.current)
        setError(e instanceof Error ? e.message : "读取失败")
    }
  }
  return {
    selected,
    seed,
    current,
    digest,
    licenseText,
    error,
    confirmed,
    setConfirmed,
    reviewRequired,
    preview,
    failed: (message: string) => {
      setError(message)
      setConfirmed(false)
      setReviewRequired(true)
    },
    close: () => {
      request.current++
      setSelected(null)
      setSeed(null)
      setConfirmed(false)
    },
  }
}
