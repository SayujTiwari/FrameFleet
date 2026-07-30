import {
  type ChangeEvent,
  type SyntheticEvent,
  useEffect,
  useState,
} from 'react'
import './App.css'
import {
  createEncodingJob,
  type EncodingJob,
} from './api/createEncodingJob'
import { planSegments } from './video/planSegments'

const TARGET_SEGMENT_SECONDS = 30

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
  const [showAllSegments, setShowAllSegments] = useState(false)
  const [encodingJob, setEncodingJob] = useState<EncodingJob | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [jobError, setJobError] = useState<string | null>(null)

  const plannedSegments = videoDetails
    ? planSegments(videoDetails.durationSeconds, TARGET_SEGMENT_SECONDS)
    : []

  const visibleSegments = showAllSegments
    ? plannedSegments
    : plannedSegments.slice(0, 5)

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
    setShowAllSegments(false)
    setEncodingJob(null)
    setUploadProgress(0)
    setJobError(null)
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

  async function handleCreateJob() {
    if (!selectedFile || !videoDetails) {
      return
    }

    setIsUploading(true)
    setUploadProgress(0)
    setEncodingJob(null)
    setJobError(null)

    try {
      const job = await createEncodingJob({
        video: selectedFile,
        targetSegmentSeconds: TARGET_SEGMENT_SECONDS,
        onProgress: setUploadProgress,
      })

      setEncodingJob(job)
    } catch (error) {
      setJobError(
        error instanceof Error ? error.message : 'Could not create the job',
      )
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <main>
      <p>Faster way of video encoding</p>
      <h1>FrameFleet</h1>
      <p>Choose a video to inspect before creating an encoding job.</p>
      
      <input
        type="file"
        accept="video/*"
        disabled={isUploading}
        onChange={handleFileChange}
      />

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

      {plannedSegments.length > 0 && (
        <section>
          <h2>Segment plan</h2>
          <p>
            {plannedSegments.length} segments, each up to{' '}
            {TARGET_SEGMENT_SECONDS} seconds long
          </p>

          <ol>
            {visibleSegments.map((segment) => (
              <li key={segment.index}>
                Segment {segment.index + 1}: {segment.startSeconds.toFixed(1)}–
                {segment.endSeconds.toFixed(1)} seconds
              </li>
            ))}
          </ol>

          {plannedSegments.length > 5 && (
            <button
              type="button"
              onClick={() => setShowAllSegments((current) => !current)}
            >
              {showAllSegments ? 'Show fewer segments' : 'Show all segments'}
            </button>
          )}

          <button
            type="button"
            disabled={isUploading}
            onClick={handleCreateJob}
          >
            {isUploading
              ? `Uploading ${uploadProgress}%`
              : 'Upload and create job'}
          </button>

          {isUploading && <progress value={uploadProgress} max="100" />}

          {jobError && <p role="alert">{jobError}</p>}

          {encodingJob && (
            <section>
              <h2>Backend verification</h2>
              <p>
                Job {encodingJob.job_id} is {encodingJob.status} with{' '}
                {encodingJob.segment_count} segments.
              </p>

              <dl>
                <dt>Verified duration</dt>
                <dd>{encodingJob.duration_seconds.toFixed(1)} seconds</dd>

                <dt>Verified resolution</dt>
                <dd>
                  {encodingJob.width} × {encodingJob.height}
                </dd>

                <dt>Video codec</dt>
                <dd>{encodingJob.video_codec}</dd>

                <dt>Container format</dt>
                <dd>{encodingJob.format_name}</dd>

                <dt>Audio stream</dt>
                <dd>{encodingJob.has_audio ? 'Present' : 'Not present'}</dd>
              </dl>
            </section>
          )}
        </section>
      )}
    </main>
  )
}

export default App
