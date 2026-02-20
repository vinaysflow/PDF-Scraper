/**
 * Vercel serverless proxy for GET /api/extract/async/:jobId.
 * Forwards the poll request to the backend and returns the job status/result.
 */

module.exports = async (req, res) => {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ detail: "Method not allowed" });
  }

  const base = process.env.EXTRACT_API_URL;
  if (!base || !base.startsWith("http")) {
    return res.status(503).json({
      detail:
        "EXTRACT_API_URL is not set. Deploy the PDF OCR backend (e.g. Railway or Render), then set EXTRACT_API_URL in your Vercel project environment variables.",
    });
  }

  const { jobId } = req.query;
  if (!jobId) {
    return res.status(400).json({ detail: "Missing job ID." });
  }

  const targetUrl =
    base.replace(/\/$/, "") + "/api/extract/async/" + encodeURIComponent(jobId);

  try {
    const headers = { Accept: "application/json" };
    if (req.headers["x-api-key"]) {
      headers["X-API-Key"] = req.headers["x-api-key"];
    }

    const response = await fetch(targetUrl, { method: "GET", headers });

    const text = await response.text();
    res.status(response.status);
    res.setHeader("Content-Type", "application/json");
    try {
      res.send(text);
    } catch {
      res.json({ detail: "Invalid response from backend" });
    }
  } catch (err) {
    console.error("Proxy error (async GET):", err.message);
    res.status(502).json({
      detail:
        err.message ||
        "Backend request failed. Check EXTRACT_API_URL and that the backend is running.",
    });
  }
};
