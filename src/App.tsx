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

const STATUS_LABELS: Record<EncodingJob['status'], string> = {
  ready: 'Queued',
  processing: 'Encoding',
  assembling: 'Assembling',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

function getJobProgress(job: EncodingJob): number {
  if (job.status === 'completed') {
    return 100
  }

  if (job.segment_count === 0) {
    return 0
  }

  return Math.round((job.completed_segments / job.segment_count) * 100)
}

function formatFileSize(sizeBytes: number): string {
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`
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
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="FrameFleet home">
          <span className="brand-mark" aria-hidden="true">
            FF
          </span>
          FrameFleet
        </a>
        <div className="fleet-status">
          <span className="status-light" aria-hidden="true" />
          Local fleet ready
        </div>
      </header>

      <section className="hero-section" id="top">
        <div className="hero-glow" aria-hidden="true" />
        <p className="eyebrow">Distributed video encoding</p>
        <h1>
          One video.
          <br />
          <span>A fleet of workers.</span>
        </h1>
        <p className="hero-copy">
          Split large exports into independent segments, process them in
          parallel, and assemble the result automatically.
        </p>
        <a className="primary-button hero-action" href="#workspace">
          Create an export <span aria-hidden="true">↓</span>
        </a>
        <div className="feature-row" aria-label="FrameFleet features">
          <span>Parallel segments</span>
          <span>Automatic recovery</span>
          <span>Durable job history</span>
        </div>
      </section>

      <section className="content-section" id="workspace">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Export workspace</p>
            <h2>Prepare your video</h2>
          </div>
          <p>Select a source, verify its details, and configure the export.</p>
        </div>

        <div className="workspace-grid">
          <section className="glossy-card preview-card">
            <div className="card-heading">
              <div>
                <p className="card-label">01 / Source</p>
                <h3>Video preview</h3>
              </div>
              {videoDetails && <span className="ready-chip">Ready</span>}
            </div>

            {videoUrl ? (
              <video
                className="video-preview"
                src={videoUrl}
                controls
                preload="metadata"
                onLoadedMetadata={handleMetadataLoaded}
              />
            ) : (
              <div className="preview-placeholder">
                <span className="upload-symbol" aria-hidden="true">
                  ↑
                </span>
                <strong>No video selected</strong>
                <span>MP4, MOV, WebM, or another browser-supported video</span>
              </div>
            )}

            <input
              className="file-input"
              id="video-upload"
              type="file"
              accept="video/*"
              disabled={isUploading}
              onChange={handleFileChange}
            />
            <label className="file-picker" htmlFor="video-upload">
              <span>{videoUrl ? 'Choose a different video' : 'Choose video'}</span>
              <span aria-hidden="true">Browse files ↗</span>
            </label>

            {videoDetails && (
              <dl className="metadata-grid">
                <div>
                  <dt>Filename</dt>
                  <dd title={videoDetails.name}>{videoDetails.name}</dd>
                </div>
                <div>
                  <dt>File size</dt>
                  <dd>{videoDetails.sizeMb.toFixed(1)} MB</dd>
                </div>
                <div>
                  <dt>Duration</dt>
                  <dd>{videoDetails.durationSeconds.toFixed(1)} sec</dd>
                </div>
                <div>
                  <dt>Resolution</dt>
                  <dd>
                    {videoDetails.width} × {videoDetails.height}
                  </dd>
                </div>
              </dl>
            )}
          </section>

          <section className="glossy-card settings-card">
            <div className="card-heading">
              <div>
                <p className="card-label">02 / Configure</p>
                <h3>Export settings</h3>
              </div>
              {plannedSegments.length > 0 && (
                <span className="segment-count">
                  {plannedSegments.length} segments
                </span>
              )}
            </div>

            {plannedSegments.length === 0 ? (
              <div className="settings-placeholder">
                <span>02</span>
                <p>Video settings will appear after you select a source.</p>
              </div>
            ) : (
              <>
                <fieldset className="settings-fields" disabled={isUploading}>
                  <label>
                    <span>Resolution</span>
                    <select
                      value={outputResolution}
                      onChange={(event) =>
                        setOutputResolution(
                          event.target.value as OutputResolution,
                        )
                      }
                    >
                      <option value="original">Original</option>
                      <option value="1080p">1080p</option>
                      <option value="720p">720p</option>
                      <option value="480p">480p</option>
                    </select>
                  </label>

                  <label>
                    <span>Quality</span>
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

                <div className="segment-plan">
                  <div className="subheading-row">
                    <h4>Segment plan</h4>
                    <span>Up to {TARGET_SEGMENT_SECONDS}s each</span>
                  </div>
                  <ol className="segment-list">
                    {visibleSegments.map((segment) => (
                      <li key={segment.index}>
                        <span>{String(segment.index + 1).padStart(2, '0')}</span>
                        <strong>
                          {segment.startSeconds.toFixed(1)}–
                          {segment.endSeconds.toFixed(1)}s
                        </strong>
                      </li>
                    ))}
                  </ol>

                  {plannedSegments.length > 5 && (
                    <button
                      className="text-button"
                      type="button"
                      onClick={() => setShowAllSegments((current) => !current)}
                    >
                      {showAllSegments
                        ? 'Show fewer segments'
                        : `Show all ${plannedSegments.length} segments`}
                    </button>
                  )}
                </div>

                <button
                  className="primary-button create-button"
                  type="button"
                  disabled={isUploading}
                  onClick={handleCreateJob}
                >
                  {isUploading
                    ? `Uploading ${uploadProgress}%`
                    : 'Start distributed export'}
                  <span aria-hidden="true">→</span>
                </button>

                {isUploading && (
                  <div className="upload-progress" aria-live="polite">
                    <div>
                      <span>Uploading source</span>
                      <span>{uploadProgress}%</span>
                    </div>
                    <progress value={uploadProgress} max="100" />
                  </div>
                )}
              </>
            )}

            {jobError && (
              <p className="error-message" role="alert">
                {jobError}
              </p>
            )}
          </section>
        </div>
      </section>

      {encodingJob && (
        <section className="content-section job-section" aria-live="polite">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Live export</p>
              <h2>{encodingJob.file_name}</h2>
            </div>
            <span className={`status-badge status-${encodingJob.status}`}>
              {STATUS_LABELS[encodingJob.status]}
            </span>
          </div>

          <div className="glossy-card job-card">
            <div className="job-progress-heading">
              <div>
                <strong>{getJobProgress(encodingJob)}%</strong>
                <span>overall progress</span>
              </div>
              <p>
                {encodingJob.completed_segments} of {encodingJob.segment_count}{' '}
                segments encoded
              </p>
            </div>
            <progress
              className="job-progress"
              value={getJobProgress(encodingJob)}
              max="100"
            />

            <div className="job-message-row">
              <div>
                {(encodingJob.status === 'ready' ||
                  encodingJob.status === 'processing') && (
                  <p>Workers are processing independent ranges in parallel.</p>
                )}
                {encodingJob.status === 'assembling' && (
                  <p>All segments are ready. Assembling the final video…</p>
                )}
                {encodingJob.status === 'completed' && (
                  <p>Your export is assembled and ready to download.</p>
                )}
                {encodingJob.status === 'failed' && (
                  <p className="error-message" role="alert">
                    The export could not be completed.
                  </p>
                )}
                {encodingJob.status === 'cancelled' && (
                  <p>This export was cancelled before completion.</p>
                )}
                {encodingJob.retry_count > 0 && (
                  <span className="retry-note">
                    {encodingJob.retry_count} worker{' '}
                    {encodingJob.retry_count === 1 ? 'retry' : 'retries'}
                  </span>
                )}
              </div>

              {encodingJob.status === 'completed' && (
                <a
                  className="primary-button compact-button"
                  href={getEncodingJobDownloadUrl(encodingJob.job_id)}
                >
                  Download export ↓
                </a>
              )}

              {(encodingJob.status === 'ready' ||
                encodingJob.status === 'processing') && (
                <button
                  className="secondary-button compact-button"
                  type="button"
                  disabled={cancellingJobId === encodingJob.job_id}
                  onClick={() => handleCancelJob(encodingJob)}
                >
                  {cancellingJobId === encodingJob.job_id
                    ? 'Cancelling…'
                    : 'Cancel export'}
                </button>
              )}
            </div>

            <dl className="job-detail-grid">
              <div>
                <dt>Export ID</dt>
                <dd>{encodingJob.job_id.slice(0, 8)}</dd>
              </div>
              <div>
                <dt>Output</dt>
                <dd>
                  {encodingJob.export_settings?.output_height
                    ? `${encodingJob.export_settings.output_height}p`
                    : 'Original'}
                </dd>
              </div>
              <div>
                <dt>Quality</dt>
                <dd>{encodingJob.export_settings?.quality ?? 'Balanced'}</dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>
                  {encodingJob.width} × {encodingJob.height}
                </dd>
              </div>
              <div>
                <dt>Codec</dt>
                <dd>{encodingJob.video_codec}</dd>
              </div>
              <div>
                <dt>Audio</dt>
                <dd>{encodingJob.has_audio ? 'Included' : 'None'}</dd>
              </div>
            </dl>
          </div>
        </section>
      )}

      <section className="content-section history-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Job history</p>
            <h2>Recent exports</h2>
          </div>
          <p>Durable records from your latest encoding jobs.</p>
        </div>

        {historyError && (
          <p className="error-message" role="alert">
            {historyError}
          </p>
        )}

        {recentJobs.length === 0 ? (
          <div className="empty-history glossy-card">
            <span aria-hidden="true">◇</span>
            <h3>No exports yet</h3>
            <p>Your completed and active jobs will appear here.</p>
          </div>
        ) : (
          <ol className="history-list">
            {recentJobs.map((job) => (
              <li className="history-card glossy-card" key={job.job_id}>
                <div className="history-main">
                  <div className="file-icon" aria-hidden="true">
                    ▶
                  </div>
                  <div className="history-copy">
                    <div className="history-title-row">
                      <strong title={job.file_name}>{job.file_name}</strong>
                      <span className={`status-badge status-${job.status}`}>
                        {STATUS_LABELS[job.status]}
                      </span>
                    </div>
                    <p>
                      {formatFileSize(job.file_size_bytes)} ·{' '}
                      {job.segment_count} segments ·{' '}
                      {new Date(job.created_at).toLocaleString()}
                    </p>
                    <div className="history-progress-row">
                      <progress value={getJobProgress(job)} max="100" />
                      <span>{getJobProgress(job)}%</span>
                    </div>
                  </div>
                </div>

                <div className="history-actions">
                  {job.status === 'completed' && (
                    <a href={getEncodingJobDownloadUrl(job.job_id)}>
                      Download ↓
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
                        : 'Cancel'}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      <footer>
        <a className="brand footer-brand" href="#top">
          <span className="brand-mark" aria-hidden="true">
            FF
          </span>
          FrameFleet
        </a>
        <p>Distributed exports, built from first principles.</p>
      </footer>
    </main>
  )
}

export default App
