/**
 * Vercel serverless proxy for POST /api/extract/async.
 * Forwards the multipart upload to the backend's async extraction endpoint.
 */

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ detail: "Method not allowed" });
  }

  const base = process.env.EXTRACT_API_URL;
  if (!base || !base.startsWith("http")) {
    return res.status(503).json({
      detail:
        "EXTRACT_API_URL is not set. Deploy the PDF OCR backend (e.g. Railway or Render), then set EXTRACT_API_URL in your Vercel project environment variables.",
    });
  }

  const query = req.url && req.url.includes("?") ? req.url.split("?")[1] : "";
  const targetUrl =
    base.replace(/\/$/, "") + "/api/extract/async" + (query ? "?" + query : "");

  try {
    const body = await new Promise((resolve, reject) => {
      const chunks = [];
      req.on("data", (chunk) => chunks.push(chunk));
      req.on("end", () => resolve(Buffer.concat(chunks)));
      req.on("error", reject);
    });

    const headers = {
      "Content-Type": req.headers["content-type"] || "application/octet-stream",
      Accept: "application/json",
    };
    if (req.headers["x-api-key"]) {
      headers["X-API-Key"] = req.headers["x-api-key"];
    }

    const response = await fetch(targetUrl, {
      method: "POST",
      body,
      headers,
    });

    const text = await response.text();
    res.status(response.status);
    res.setHeader("Content-Type", "application/json");
    try {
      res.send(text);
    } catch {
      res.json({ detail: "Invalid response from backend" });
    }
  } catch (err) {
    console.error("Proxy error (async POST):", err.message);
    res.status(502).json({
      detail:
        err.message ||
        "Backend request failed. Check EXTRACT_API_URL and that the backend is running.",
    });
  }
};
