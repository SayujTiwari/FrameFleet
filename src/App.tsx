import {
  type ChangeEvent,
  type SyntheticEvent,
  useEffect,
  useState,
} from 'react'
import './App.css'
import {
  cancelEncodingJob,
  createEncodingJob,
  getEncodingJob,
  getEncodingJobDownloadUrl,
  listEncodingJobs,
  type EncodingJob,
  type OutputResolution,
  type QualityProfile,
} from './api/createEncodingJob'
import { planSegments } from './video/planSegments'

const TARGET_SEGMENT_SECONDS = 30
const MAX_RECENT_JOBS = 20

// video data
type VideoDetails = {
  name: string
  type: string
  sizeMb: number
  durationSeconds: number
  width: number
  height: number
}

// insert and sort by newest
function addOrUpdateRecentJob(
  jobs: EncodingJob[],
  updatedJob: EncodingJob,
): EncodingJob[] {
  return [updatedJob, ...jobs.filter((job) => job.job_id !== updatedJob.job_id)] // remove if old version
    .sort(
      (first, second) =>
        Date.parse(second.created_at) - Date.parse(first.created_at),
    )
    .slice(0, MAX_RECENT_JOBS) 
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
  const [recentJobs, setRecentJobs] = useState<EncodingJob[]>([])
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [cancellingJobId, setCancellingJobId] = useState<string | null>(null)
  const [outputResolution, setOutputResolution] =
    useState<OutputResolution>('original')
  const [quality, setQuality] = useState<QualityProfile>('balanced')
  const encodingJobId = encodingJob?.job_id
  const encodingJobStatus = encodingJob?.status
  const hasActiveRecentJobs = recentJobs.some(
    (job) =>
      job.status === 'ready' ||
      job.status === 'processing' ||
      job.status === 'assembling',
  )

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

  // load recent jobs
  useEffect(() => {
    let cancelled = false

    async function loadRecentJobs() {
      try {
        const jobs = await listEncodingJobs(MAX_RECENT_JOBS)

        if (!cancelled) {
          setRecentJobs(jobs)
          setHistoryError(null)
        }
      } catch {
        if (!cancelled) {
          setHistoryError('Could not load recent exports')
        }
      }
    }

    void loadRecentJobs()

    return () => {
      cancelled = true
    }
  }, [])

  // polling while one job active
  useEffect(() => {
    if (!hasActiveRecentJobs) {
      return
    }

    let cancelled = false
    const intervalId = window.setInterval(async () => {
      try {
        const jobs = await listEncodingJobs(MAX_RECENT_JOBS)

        if (!cancelled) {
          setRecentJobs(jobs)
          setHistoryError(null)
        }
      } catch {
        if (!cancelled) {
          setHistoryError('Could not refresh recent exports')
        }
      }
    }, 2000)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [hasActiveRecentJobs])

  useEffect(() => {
    if (
      !encodingJobId ||
      cancellingJobId === encodingJobId ||
      encodingJobStatus === 'completed' ||
      encodingJobStatus === 'failed' ||
      encodingJobStatus === 'cancelled'
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
          setRecentJobs((currentJobs) =>
            addOrUpdateRecentJob(currentJobs, updatedJob),
          )
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
  }, [encodingJobId, encodingJobStatus, cancellingJobId])

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
      setRecentJobs((currentJobs) => addOrUpdateRecentJob(currentJobs, job))
    } catch (error) {
      setJobError(
        error instanceof Error ? error.message : 'Could not create the job',
      )
    } finally {
      setIsUploading(false)
    }
  }

  async function handleCancelJob(job: EncodingJob) {
    setCancellingJobId(job.job_id)
    setJobError(null)
    setHistoryError(null)

    try {
      const cancelledJob = await cancelEncodingJob(job.job_id)
      setEncodingJob((currentJob) =>
        currentJob?.job_id === job.job_id ? cancelledJob : currentJob,
      )
      setRecentJobs((currentJobs) =>
        addOrUpdateRecentJob(currentJobs, cancelledJob),
      )
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Could not cancel the job'
      setJobError(message)
      setHistoryError(message)
    } finally {
      setCancellingJobId((currentJobId) =>
        currentJobId === job.job_id ? null : currentJobId,
      )
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
                <>
                  <p>The background workers are encoding the video segments…</p>
                  <button
                    type="button"
                    disabled={cancellingJobId === encodingJob.job_id}
                    onClick={() => handleCancelJob(encodingJob)}
                  >
                    {cancellingJobId === encodingJob.job_id
                      ? 'Cancelling…'
                      : 'Cancel export'}
                  </button>
                </>
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

              {encodingJob.status === 'cancelled' && (
                <p>The video export was cancelled.</p>
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

      <section>
        <h2>Recent exports</h2>

        {historyError && <p role="alert">{historyError}</p>}

        {recentJobs.length === 0 ? (
          <p>No exports yet.</p>
        ) : (
          <ol>
            {recentJobs.map((job) => (
              <li key={job.job_id}>
                <strong>{job.file_name}</strong>
                <p>
                  {job.status} · {job.completed_segments} of {job.segment_count}{' '}
                  segments complete
                </p>
                <p>{new Date(job.created_at).toLocaleString()}</p>

                {job.status === 'completed' && (
                  <a href={getEncodingJobDownloadUrl(job.job_id)}>
                    Download video
                  </a>
                )}

                {(job.status === 'ready' || job.status === 'processing') && (
                  <button
                    type="button"
                    disabled={cancellingJobId === job.job_id}
                    onClick={() => handleCancelJob(job)}
                  >
                    {cancellingJobId === job.job_id
                      ? 'Cancelling…'
                      : 'Cancel export'}
                  </button>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>
    </main>
  )
}

export default App
