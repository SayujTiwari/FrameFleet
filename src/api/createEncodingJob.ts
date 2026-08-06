export type OutputResolution = 'original' | '1080p' | '720p' | '480p'
export type QualityProfile = 'high' | 'balanced' | 'compact'

export type EncodingJob = {
  job_id: string
  created_at: string
  status:
    | 'ready'
    | 'processing'
    | 'assembling'
    | 'completed'
    | 'failed'
    | 'cancelled'
  file_name: string
  file_size_bytes: number
  duration_seconds: number
  target_segment_seconds: number
  segment_count: number
  completed_segments: number
  retry_count: number
  export_settings: {
    resolution: OutputResolution
    output_height: number | null
    quality: QualityProfile
  } | null
  size_constraint: {
    target_size_bytes: number
    video_bitrate_bps: number
    audio_bitrate_bps: number
    adjustment_count: number
    last_output_size_bytes: number | null
  } | null
  output_file_size_bytes: number | null
  width: number
  height: number
  video_codec: string
  format_name: string
  has_audio: boolean
}

export type DeliveryOutputRequest = {
  name: string
  resolution: OutputResolution
  quality: QualityProfile
  max_file_size_mb: number | null
}

export type DeliveryOutput = {
  name: string
  job: EncodingJob
}

export type DeliveryBatch = {
  batch_id: string
  created_at: string
  file_name: string
  file_size_bytes: number
  duration_seconds: number
  width: number
  height: number
  video_codec: string
  format_name: string
  has_audio: boolean
  outputs: DeliveryOutput[]
}

const API_BASE_URL = 'http://127.0.0.1:8000'

export async function listEncodingJobs(limit = 20): Promise<EncodingJob[]> {
  const response = await fetch(`${API_BASE_URL}/jobs?limit=${limit}`)
  const body = await response.json()

  if (!response.ok) {
    throw new Error(
      typeof body.detail === 'string'
        ? body.detail
        : `Backend returned status ${response.status}`,
    )
  }

  return body as EncodingJob[]
}

export async function getEncodingJob(jobId: string): Promise<EncodingJob> {
  const response = await fetch(`${API_BASE_URL}/jobs/${jobId}`)
  const body = await response.json()

  if (!response.ok) {
    throw new Error(
      typeof body.detail === 'string'
        ? body.detail
        : `Backend returned status ${response.status}`,
    )
  }

  return body as EncodingJob
}

export async function getDeliveryBatch(
  batchId: string,
): Promise<DeliveryBatch> {
  const response = await fetch(`${API_BASE_URL}/deliveries/${batchId}`)
  const body = await response.json()

  if (!response.ok) {
    throw new Error(
      typeof body.detail === 'string'
        ? body.detail
        : `Backend returned status ${response.status}`,
    )
  }

  return body as DeliveryBatch
}

export async function cancelEncodingJob(jobId: string): Promise<EncodingJob> {
  const response = await fetch(`${API_BASE_URL}/jobs/${jobId}/cancel`, {
    method: 'POST',
  })
  const body = await response.json()

  if (!response.ok) {
    throw new Error(
      typeof body.detail === 'string'
        ? body.detail
        : `Backend returned status ${response.status}`,
    )
  }

  return body as EncodingJob
}

export function getEncodingJobDownloadUrl(jobId: string): string {
  return `${API_BASE_URL}/jobs/${jobId}/download`
}

type CreateEncodingJobOptions = {
  video: File
  targetSegmentSeconds: number
  outputResolution: OutputResolution
  quality: QualityProfile
  onProgress: (percentage: number) => void
}

export function createEncodingJob({
  video,
  targetSegmentSeconds,
  outputResolution,
  quality,
  onProgress,
}: CreateEncodingJobOptions): Promise<EncodingJob> {
  const formData = new FormData()
  formData.append('video', video)
  formData.append('target_segment_seconds', targetSegmentSeconds.toString())
  formData.append('output_resolution', outputResolution)
  formData.append('quality', quality)

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', `${API_BASE_URL}/jobs`)
    request.responseType = 'json'

    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    })

    request.addEventListener('load', () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(request.response as EncodingJob)
        return
      }

      const detail = request.response?.detail
      reject(
        new Error(
          typeof detail === 'string'
            ? detail
            : `Backend returned status ${request.status}`,
        ),
      )
    })

    request.addEventListener('error', () => {
      reject(new Error('Could not connect to the backend'))
    })

    request.send(formData)
  })
}

type CreateDeliveryBatchOptions = {
  video: File
  targetSegmentSeconds: number
  outputs: DeliveryOutputRequest[]
  onProgress: (percentage: number) => void
}

export function createDeliveryBatch({
  video,
  targetSegmentSeconds,
  outputs,
  onProgress,
}: CreateDeliveryBatchOptions): Promise<DeliveryBatch> {
  const formData = new FormData()
  formData.append('video', video)
  formData.append('target_segment_seconds', targetSegmentSeconds.toString())
  formData.append('outputs', JSON.stringify(outputs))

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', `${API_BASE_URL}/deliveries`)
    request.responseType = 'json'

    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    })

    request.addEventListener('load', () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(request.response as DeliveryBatch)
        return
      }

      const detail = request.response?.detail
      reject(
        new Error(
          typeof detail === 'string'
            ? detail
            : `Backend returned status ${request.status}`,
        ),
      )
    })

    request.addEventListener('error', () => {
      reject(new Error('Could not connect to the backend'))
    })

    request.send(formData)
  })
}
