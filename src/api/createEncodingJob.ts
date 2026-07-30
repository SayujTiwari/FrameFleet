export type EncodingJob = {
  job_id: string
  status: 'ready'
  file_name: string
  file_size_bytes: number
  duration_seconds: number
  target_segment_seconds: number
  segment_count: number
  width: number
  height: number
  video_codec: string
  format_name: string
  has_audio: boolean
}

type CreateEncodingJobOptions = {
  video: File
  targetSegmentSeconds: number
  onProgress: (percentage: number) => void
}

export function createEncodingJob({
  video,
  targetSegmentSeconds,
  onProgress,
}: CreateEncodingJobOptions): Promise<EncodingJob> {
  const formData = new FormData()
  formData.append('video', video)
  formData.append('target_segment_seconds', targetSegmentSeconds.toString())

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', 'http://127.0.0.1:8000/jobs')
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
