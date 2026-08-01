/**
 * Reserved media slot — mirrors the framed placeholder on the Framer site
 * where the product walkthrough video will be dropped in.
 */
export function MediaShowcase() {
  return (
    <section className="mx-auto w-full max-w-[1180px] px-6 py-10">
      <div className="border-border bg-surface rounded-[28px] border p-8 sm:p-12">
        <div className="border-border bg-surface-tint aspect-video w-full rounded-2xl border border-dashed" />
      </div>
    </section>
  )
}
