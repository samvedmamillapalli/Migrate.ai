/**
 * Product walkthrough clip on the landing page, front and center. Rendered
 * as a native <video> (autoplay/loop/muted/playsInline) rather than an
 * actual GIF — the source export was a 54MB animated GIF of the same clip;
 * a browser-native looping video is the standard "autoplaying GIF"
 * replacement and is a fraction of the size (~4MB) for the same result.
 * `muted` is required for autoplay to be allowed at all in every major
 * browser, and `playsInline` stops iOS Safari from forcing fullscreen.
 */
export function MediaShowcase() {
  return (
    <section className="mx-auto w-full max-w-[1180px] px-6 py-10">
      <div className="border-border bg-surface rounded-[28px] border p-8 sm:p-12">
        <video
          className="aspect-video w-full rounded-2xl object-cover"
          src="/hero-demo.mp4"
          poster="/hero-demo-poster.jpg"
          autoPlay
          loop
          muted
          playsInline
          preload="auto"
        />
      </div>
    </section>
  )
}
