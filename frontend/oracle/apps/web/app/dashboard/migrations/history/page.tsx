export default function PastMigrationsPage() {
  return (
    <div className="flex flex-1 flex-col gap-1 px-4 pb-6 md:px-6">
      <h1 className="text-foreground text-2xl font-medium tracking-tight">
        Past Migrations
      </h1>
      <p className="text-muted-foreground text-sm">
        Review previous migration runs and their shadow execution results.
      </p>
    </div>
  )
}
