import {
  type ChangeEvent,
  type SyntheticEvent,
  useEffect,
  useState,
} from 'react'
import './App.css'
import {
  cancelEncodingJob,
  createDeliveryBatch,
  getDeliveryBatch,
  getEncodingJobDownloadUrl,
  listEncodingJobs,
  type DeliveryBatch,
  type DeliveryOutputRequest,
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

type DeliveryOutputDraft = DeliveryOutputRequest & {
  id: string
}

const DEFAULT_DELIVERY_OUTPUTS: DeliveryOutputDraft[] = [
  {
    id: 'archive-master',
    name: 'Archive master',
    resolution: 'original',
    quality: 'high',
    max_file_size_mb: null,
  },
  {
    id: 'social-hd',
    name: 'Social HD',
    resolution: '1080p',
    quality: 'balanced',
    max_file_size_mb: null,
  },
  {
    id: 'web-preview',
    name: 'Web preview',
    resolution: '720p',
    quality: 'compact',
    max_file_size_mb: null,
  },
]

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

// average between all ouputs and where they at
function getBatchProgress(batch: DeliveryBatch): number {
  if (batch.outputs.length === 0) {
    return 0
  }

  const totalProgress = batch.outputs.reduce(
    (sum, output) => sum + getJobProgress(output.job),
    0,
  )
  return Math.round(totalProgress / batch.outputs.length)
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

function addBatchJobsToHistory(
  jobs: EncodingJob[],
  batch: DeliveryBatch,
): EncodingJob[] {
  return batch.outputs.reduce(
    (currentJobs, output) => addOrUpdateRecentJob(currentJobs, output.job),
    jobs,
  )
}

// main func
function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)  // the actaul file object
  const [videoUrl, setVideoUrl] = useState<string | null>(null) // temporary url that <video> can read
  const [videoDetails, setVideoDetails] = useState<VideoDetails | null>(null) // metadata
  const [deliveryOutputs, setDeliveryOutputs] = useState<
    DeliveryOutputDraft[]
  >(DEFAULT_DELIVERY_OUTPUTS)
  const [deliveryBatch, setDeliveryBatch] = useState<DeliveryBatch | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [jobError, setJobError] = useState<string | null>(null)
  const [recentJobs, setRecentJobs] = useState<EncodingJob[]>([])
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [cancellingJobId, setCancellingJobId] = useState<string | null>(null)
  const deliveryBatchId = deliveryBatch?.batch_id
  const hasActiveDelivery = deliveryBatch?.outputs.some(
    ({ job }) =>
      job.status === 'ready' ||
      job.status === 'processing' ||
      job.status === 'assembling',
  )
  const hasActiveRecentJobs = recentJobs.some(
    (job) =>
      job.status === 'ready' ||
      job.status === 'processing' ||
      job.status === 'assembling',
  )

  const plannedSegments = videoDetails
    ? planSegments(videoDetails.durationSeconds, TARGET_SEGMENT_SECONDS)
    : []

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
    if (!deliveryBatchId || !hasActiveDelivery) {
      return
    }

    let cancelled = false
    const intervalId = window.setInterval(async () => {
      try {
        const updatedBatch = await getDeliveryBatch(deliveryBatchId)

        if (!cancelled) {
          setDeliveryBatch(updatedBatch)
          setRecentJobs((currentJobs) =>
            addBatchJobsToHistory(currentJobs, updatedBatch),
          )
          setJobError(null)
        }
      } catch {
        if (!cancelled) {
          setJobError('Could not refresh the delivery status')
        }
      }
    }, 1000)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [deliveryBatchId, hasActiveDelivery])

  // new file is selected
  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null

    setSelectedFile(file)
    setVideoDetails(null) // clear old 
    setDeliveryBatch(null)
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

  function updateDeliveryOutput(
    outputId: string,
    changes: Partial<DeliveryOutputRequest>,
  ) {
    setDeliveryOutputs((currentOutputs) =>
      currentOutputs.map((output) =>
        output.id === outputId ? { ...output, ...changes } : output,
      ),
    )
  }

  function addDeliveryOutput() {
    // no more than 6 outputs
    if (deliveryOutputs.length >= 6) {
      return
    }
    // possible resolutions
    const resolutions: OutputResolution[] = [
      'original',
      '1080p',
      '720p',
      '480p',
    ]
    const qualities: QualityProfile[] = ['high', 'balanced', 'compact']
    const nextConfiguration = resolutions
      .flatMap((resolution) =>
        qualities.map((quality) => ({ resolution, quality })),
      )
      .find(
        (configuration) =>
          !deliveryOutputs.some(
            (output) =>
              output.resolution === configuration.resolution &&
              output.quality === configuration.quality,
          ),
      )

    if (!nextConfiguration) {
      return
    }

    // change react state
    setDeliveryOutputs((currentOutputs) => [
      ...currentOutputs,
      {
        id: crypto.randomUUID(),  // unique browser id
        name: `Output ${currentOutputs.length + 1}`,
        max_file_size_mb: null,
        ...nextConfiguration,
      },
    ])
  }

  function removeDeliveryOutput(outputId: string) {
    setDeliveryOutputs((currentOutputs) =>
      currentOutputs.length === 1
        ? currentOutputs
        : currentOutputs.filter((output) => output.id !== outputId),
    )
  }

  async function handleCreateDelivery() {
    if (!selectedFile || !videoDetails) {
      return
    }

    const outputs = deliveryOutputs.map(
      ({ name, resolution, quality, max_file_size_mb }) => ({
        name: name.trim(), // remove extra spaces
        resolution,
        quality,
        max_file_size_mb,
      }),
    )
    const names = outputs.map((output) => output.name.toLocaleLowerCase())
    const configurations = outputs.map(
      (output) => `${output.resolution}:${output.quality}`,
    )

    if (outputs.some((output) => output.name.length === 0)) {
      setJobError('Every output needs a name')
      return
    }

    if (
      outputs.some(
        (output) =>
          output.max_file_size_mb !== null &&
          (!Number.isFinite(output.max_file_size_mb) ||
            output.max_file_size_mb < 1 ||
            output.max_file_size_mb > 50_000),
      )
    ) {
      setJobError('Maximum file size must be between 1 and 50,000 MB')
      return
    }

    if (new Set(names).size !== names.length) {
      setJobError('Every output needs a unique name')
      return
    }

    if (new Set(configurations).size !== configurations.length) {
      setJobError('Every output needs a unique resolution and quality pair')
      return
    }

    setIsUploading(true)
    setUploadProgress(0)
    setDeliveryBatch(null)
    setJobError(null)

    try {
      const batch = await createDeliveryBatch({
        video: selectedFile,
        targetSegmentSeconds: TARGET_SEGMENT_SECONDS,
        outputs,
        onProgress: setUploadProgress,
      })

      setDeliveryBatch(batch)
      setRecentJobs((currentJobs) =>
        addBatchJobsToHistory(currentJobs, batch),  // add to recent history
      )
    } catch (error) {
      setJobError(
        error instanceof Error
          ? error.message
          : 'Could not create the delivery batch',
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
      // replace the cancelled job
      setDeliveryBatch((currentBatch) =>
        currentBatch
          ? {
              ...currentBatch,
              outputs: currentBatch.outputs.map((output) =>
                output.job.job_id === job.job_id
                  ? { ...output, job: cancelledJob }
                  : output,
              ),
            }
          : currentBatch,
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
        <p className="eyebrow">Multi-format video delivery</p>
        <h1>
          One master.
          <br />
          <span>Every delivery format.</span>
        </h1>
        <p className="hero-copy">
          Upload once, configure the versions you need, and let a fault-tolerant
          worker fleet produce every export in parallel.
        </p>
        <a className="primary-button hero-action" href="#workspace">
          Create an export <span aria-hidden="true">↓</span>
        </a>
        <div className="feature-row" aria-label="FrameFleet features">
          <span>One source upload</span>
          <span>Parallel renditions</span>
          <span>Automatic recovery</span>
        </div>
      </section>

      <section className="content-section" id="workspace">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Export workspace</p>
            <h2>Prepare your video</h2>
          </div>
          <p>Select a source and configure every file you need to deliver.</p>
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
                <h3>Delivery outputs</h3>
              </div>
              {plannedSegments.length > 0 && (
                <span className="segment-count">
                  {deliveryOutputs.length} outputs
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
                <fieldset className="output-list" disabled={isUploading}>
                  <legend className="sr-only">Requested delivery outputs</legend>

                  {deliveryOutputs.map((output, index) => (
                    <div className="output-editor" key={output.id}>
                      <div className="output-editor-heading">
                        <span>Output {String(index + 1).padStart(2, '0')}</span>
                        <button
                          type="button"
                          disabled={deliveryOutputs.length === 1}
                          onClick={() => removeDeliveryOutput(output.id)}
                        >
                          Remove
                        </button>
                      </div>

                      <label className="output-name-field">
                        <span>Name</span>
                        <input
                          type="text"
                          value={output.name}
                          maxLength={60}
                          onChange={(event) =>
                            updateDeliveryOutput(output.id, {
                              name: event.target.value,
                            })
                          }
                        />
                      </label>

                      <div className="output-selects">
                        <label>
                          <span>Resolution</span>
                          <select
                            value={output.resolution}
                            onChange={(event) =>
                              updateDeliveryOutput(output.id, {
                                resolution: event.target
                                  .value as OutputResolution,
                              })
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
                            value={output.quality}
                            onChange={(event) =>
                              updateDeliveryOutput(output.id, {
                                quality: event.target.value as QualityProfile,
                              })
                            }
                          >
                            <option value="high">High quality</option>
                            <option value="balanced">Balanced</option>
                            <option value="compact">Smaller file</option>
                          </select>
                        </label>
                      </div>

                      <label className="output-size-field">
                        <span>Maximum file size (MB, optional)</span>
                        <input
                          type="number"
                          min="1"
                          max="50000"
                          step="1"
                          placeholder="No size limit"
                          value={output.max_file_size_mb ?? ''}
                          onChange={(event) =>
                            updateDeliveryOutput(output.id, {
                              max_file_size_mb:
                                event.target.value === ''
                                  ? null
                                  : Number(event.target.value),
                            })
                          }
                        />
                        <small>
                          Leave blank for quality-based encoding. A limit uses a
                          calculated bitrate budget.
                        </small>
                      </label>
                    </div>
                  ))}

                  <button
                    className="add-output-button"
                    type="button"
                    disabled={deliveryOutputs.length >= 6}
                    onClick={addDeliveryOutput}
                  >
                    <span aria-hidden="true">＋</span>
                    {deliveryOutputs.length >= 6
                      ? 'Maximum of 6 outputs'
                      : 'Add another output'}
                  </button>
                </fieldset>

                <div className="batch-plan">
                  <div>
                    <span>Worker tasks</span>
                    <strong>
                      {plannedSegments.length * deliveryOutputs.length}
                    </strong>
                  </div>
                  <p>
                    {plannedSegments.length} segments per output, up to{' '}
                    {TARGET_SEGMENT_SECONDS}s each
                  </p>
                </div>

                <button
                  className="primary-button create-button"
                  type="button"
                  disabled={isUploading}
                  onClick={handleCreateDelivery}
                >
                  {isUploading
                    ? `Uploading ${uploadProgress}%`
                    : `Create ${deliveryOutputs.length} exports`}
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

      {deliveryBatch && (
        <section className="content-section job-section" aria-live="polite">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Live delivery</p>
              <h2>{deliveryBatch.file_name}</h2>
            </div>
            <span className="batch-progress-chip">
              {getBatchProgress(deliveryBatch)}% complete
            </span>
          </div>

          <div className="glossy-card batch-overview">
            <div className="batch-progress-heading">
              <div>
                <strong>{getBatchProgress(deliveryBatch)}%</strong>
                <span>across {deliveryBatch.outputs.length} outputs</span>
              </div>
              <p>
                {
                  deliveryBatch.outputs.filter(
                    ({ job }) => job.status === 'completed',
                  ).length
                }{' '}
                of {deliveryBatch.outputs.length} files ready
              </p>
            </div>
            <progress
              className="job-progress"
              value={getBatchProgress(deliveryBatch)}
              max="100"
            />

            <ol className="output-progress-list">
              {deliveryBatch.outputs.map((output, index) => {
                const job = output.job

                return (
                  <li className="output-job-card" key={job.job_id}>
                    <div className="output-job-heading">
                      <div>
                        <span className="output-number">
                          {String(index + 1).padStart(2, '0')}
                        </span>
                        <div>
                          <h3>{output.name}</h3>
                          <p>
                            {job.export_settings?.resolution ?? 'original'} ·{' '}
                            {job.export_settings?.quality ?? 'balanced'} quality
                            {job.size_constraint
                              ? ` · ≤ ${formatFileSize(
                                  job.size_constraint.target_size_bytes,
                                )}`
                              : ''}
                          </p>
                        </div>
                      </div>
                      <span className={`status-badge status-${job.status}`}>
                        {STATUS_LABELS[job.status]}
                      </span>
                    </div>

                    <div className="output-job-progress">
                      <progress value={getJobProgress(job)} max="100" />
                      <span>{getJobProgress(job)}%</span>
                    </div>

                    <div className="output-job-footer">
                      <p>
                        {job.completed_segments} of {job.segment_count} segments
                        {job.retry_count > 0
                          ? ` · ${job.retry_count} retries`
                          : ''}
                        {job.size_constraint?.adjustment_count
                          ? ` · size pass ${
                              job.size_constraint.adjustment_count + 1
                            }`
                          : ''}
                        {job.output_file_size_bytes !== null
                          ? ` · ${formatFileSize(
                              job.output_file_size_bytes,
                            )} final`
                          : ''}
                      </p>

                      {job.status === 'completed' && (
                        <a href={getEncodingJobDownloadUrl(job.job_id)}>
                          Download ↓
                        </a>
                      )}

                      {(job.status === 'ready' ||
                        job.status === 'processing') && (
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
                )
              })}
            </ol>
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
                      {job.output_file_size_bytes !== null
                        ? `${formatFileSize(job.output_file_size_bytes)} output`
                        : `${formatFileSize(job.file_size_bytes)} source`}{' '}
                      ·{' '}
                      {job.export_settings?.resolution ?? 'original'} ·{' '}
                      {job.export_settings?.quality ?? 'balanced'} ·{' '}
                      {job.size_constraint
                        ? `≤ ${formatFileSize(
                            job.size_constraint.target_size_bytes,
                          )} target · `
                        : ''}
                      {job.size_constraint?.adjustment_count
                        ? `${job.size_constraint.adjustment_count} size adjustment · `
                        : ''}
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
