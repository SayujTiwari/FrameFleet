export type PlannedSegment = {
  index: number
  startSeconds: number
  endSeconds: number
  durationSeconds: number
}

// Calculate how a video should be divided
export function planSegments(
  videoDurationSeconds: number,
  targetSegmentSeconds: number,
): PlannedSegment[] {
  // Checks for errors
  if (!Number.isFinite(videoDurationSeconds) || videoDurationSeconds <= 0) {
    throw new Error('Video duration must be a positive, finite number')
  }

  if (!Number.isFinite(targetSegmentSeconds) || targetSegmentSeconds <= 0) {
    throw new Error('Target segment duration must be a positive, finite number')
  }

  
  const segmentCount = Math.ceil(
    videoDurationSeconds / targetSegmentSeconds,
  )

  return Array.from({ length: segmentCount }, (_, index) => {
    const startSeconds = index * targetSegmentSeconds  // when each seg starts

    // end of segement
    const endSeconds = Math.min(
      startSeconds + targetSegmentSeconds,
      videoDurationSeconds,
    )

    return {
      index,
      startSeconds,
      endSeconds,
      durationSeconds: endSeconds - startSeconds,
    }
  })
}
