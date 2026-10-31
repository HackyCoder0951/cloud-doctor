// Custom 404 so the exported 404.html has no inline <style>/style attributes (keeps the CSP strict).
import Link from 'next/link';

export default function NotFound() {
  return (
    <main>
      <h1>Page not found</h1>
      <p><Link href="/">Back to the overview</Link></p>
    </main>
  );
}
