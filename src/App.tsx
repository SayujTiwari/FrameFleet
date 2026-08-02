import {
  type ChangeEvent,
  type SyntheticEvent,
  useEffect,
  useState,
} from 'react'
import './App.css'
import {
  createEncodingJob,
  getEncodingJob,
  getEncodingJobDownloadUrl,
  type EncodingJob,
  type OutputResolution,
  type QualityProfile,
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
  const [outputResolution, setOutputResolution] =
    useState<OutputResolution>('original')
  const [quality, setQuality] = useState<QualityProfile>('balanced')
  const encodingJobId = encodingJob?.job_id
  const encodingJobStatus = encodingJob?.status

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

  useEffect(() => {
    if (
      !encodingJobId ||
      encodingJobStatus === 'completed' ||
      encodingJobStatus === 'failed'
    ) {
      return
    }

    let cancelled = false
    const intervalId = window.setInterval(async () => {
      try {
        const updatedJob = await getEncodingJob(encodingJobId)  // req to backend

        // if still going update components
        if (!cancelled) {
          setEncodingJob(updatedJob)
          setJobError(null)
        }
      } catch {
        if (!cancelled) {
          setJobError('Could not refresh the job status')
        }
      }
    }, 1000)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [encodingJobId, encodingJobStatus])

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
        outputResolution,
        quality,
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
          <fieldset disabled={isUploading}>
            <legend>Export settings</legend>

            <label>
              Resolution
              <select
                value={outputResolution}
                onChange={(event) =>
                  setOutputResolution(event.target.value as OutputResolution)
                }
              >
                <option value="original">Original</option>
                <option value="1080p">1080p</option>
                <option value="720p">720p</option>
                <option value="480p">480p</option>
              </select>
            </label>

            <label>
              Quality
              <select
                value={quality}
                onChange={(event) =>
                  setQuality(event.target.value as QualityProfile)
                }
              >
                <option value="high">High quality</option>
                <option value="balanced">Balanced</option>
                <option value="compact">Smaller file</option>
              </select>
            </label>
          </fieldset>

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
              <h2>Encoding job</h2>
              <p>
                Job {encodingJob.job_id} is {encodingJob.status}.{' '}
                {encodingJob.completed_segments} of {encodingJob.segment_count}{' '}
                segments are complete.
              </p>

              {encodingJob.retry_count > 0 && (
                <p>
                  Encoding retries: {encodingJob.retry_count}.
                </p>
              )}

              {(encodingJob.status === 'ready' ||
                encodingJob.status === 'processing') && (
                <p>The background workers are encoding the video segments…</p>
              )}

              {encodingJob.status === 'assembling' && (
                <p>The encoded segments are being assembled into one video…</p>
              )}

              {encodingJob.status === 'completed' && (
                <p>
                  Your export is ready.{' '}
                  <a href={getEncodingJobDownloadUrl(encodingJob.job_id)}>
                    Download video
                  </a>
                </p>
              )}

              {encodingJob.status === 'failed' && (
                <p role="alert">The video export could not be completed.</p>
              )}

              <dl>
                <dt>Output resolution</dt>
                <dd>
                  {encodingJob.export_settings?.output_height
                    ? `${encodingJob.export_settings.output_height}p`
                    : 'Original'}
                </dd>

                <dt>Quality</dt>
                <dd>{encodingJob.export_settings?.quality ?? 'Balanced'}</dd>

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
