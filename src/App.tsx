import {
  type ChangeEvent,
  type SyntheticEvent,
  useEffect,
  useState,
} from 'react'
import './App.css'

// video data
type VideoDetails = {
  name: string
  type: string
  sizeMb: number
  durationSeconds: number
  width: number
  height: number
}

// main func
function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)  // the actaul file object
  const [videoUrl, setVideoUrl] = useState<string | null>(null) // temporary url that <video> can read
  const [videoDetails, setVideoDetails] = useState<VideoDetails | null>(null) // metadata

  // prevent old urls from being retained 
  useEffect(() => {
    return () => {
      if (videoUrl) {
        URL.revokeObjectURL(videoUrl)  // no longer needed 
      }
    }
  }, [videoUrl])

  // new file is selected
  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null

    setSelectedFile(file)
    setVideoDetails(null) // clear old 
    setVideoUrl(file ? URL.createObjectURL(file) : null)
  }

  // get the file details
  function handleMetadataLoaded(event: SyntheticEvent<HTMLVideoElement>) {
    if (!selectedFile) {
      return
    }

    const video = event.currentTarget

    setVideoDetails({
      name: selectedFile.name,
      type: selectedFile.type,
      sizeMb: selectedFile.size / (1024 * 1024),
      durationSeconds: video.duration,
      width: video.videoWidth,
      height: video.videoHeight,
    })
  }

  return (
    <main>
      <p>Faster way of video encoding</p>
      <h1>FrameFleet</h1>
      <p>Choose a video to inspect before creating an encoding job.</p>
      
      <input type="file" accept="video/*" onChange={handleFileChange} />

      {videoUrl && (
        <video
          src={videoUrl}
          controls
          preload="metadata"
          onLoadedMetadata={handleMetadataLoaded}
        />
      )}

      {videoDetails && (
        <section>
          <h2>Video details</h2>

          <dl>
            <dt>Filename</dt>
            <dd>{videoDetails.name}</dd>

            <dt>File type</dt>
            <dd>{videoDetails.type}</dd>

            <dt>File size</dt>
            <dd>{videoDetails.sizeMb.toFixed(2)} MB</dd>

            <dt>Duration</dt>
            <dd>{videoDetails.durationSeconds.toFixed(1)} seconds</dd>

            <dt>Resolution</dt>
            <dd>
              {videoDetails.width} × {videoDetails.height}
            </dd>
          </dl>
        </section>
      )}
    </main>
  )
}

export default App
