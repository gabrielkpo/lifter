// The API listens on 127.0.0.1 only (uv run lifter-api); the browser calls it directly.
export const API_URL = process.env.NEXT_PUBLIC_LIFTER_API_URL ?? "http://127.0.0.1:8000";
