import { useEffect, useRef, useState } from "react"
import type { PersonaBundle } from "../shell/model.ts"
import { readArtwork } from "./pack-file.ts"

type Artwork = NonNullable<PersonaBundle["artwork"]>

export function useArtworkImport(onArtwork: (value: Artwork) => void) {
  const [error, setError] = useState("")
  const [reading, setReading] = useState(false)
  const request = useRef(0)
  useEffect(
    () => () => {
      request.current++
    },
    []
  )
  const readFile = async (file: File) => {
    const version = ++request.current
    setReading(true)
    setError("")
    try {
      const artwork = await readArtwork(file)
      if (version === request.current) onArtwork(artwork)
    } catch (e) {
      if (version === request.current)
        setError(e instanceof Error ? e.message : "图片无效")
    } finally {
      if (version === request.current) setReading(false)
    }
  }
  return { error, reading, readFile }
}
