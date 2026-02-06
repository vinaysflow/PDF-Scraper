/**
 * Vercel serverless proxy to the PDF OCR backend.
 * Set EXTRACT_API_URL in Vercel to your deployed backend (e.g. Railway, Render).
 * Extraction runs on the backend; this only forwards the request.
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
  const extractUrl = base.replace(/\/$/, "") + "/extract" + (query ? "?" + query : "");

  try {
    const body = await new Promise((resolve, reject) => {
      const chunks = [];
      req.on("data", (chunk) => chunks.push(chunk));
      req.on("end", () => resolve(Buffer.concat(chunks)));
      req.on("error", reject);
    });

    const response = await fetch(extractUrl, {
      method: "POST",
      body,
      headers: {
        "Content-Type": req.headers["content-type"] || "application/octet-stream",
        Accept: "application/json",
      },
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
    console.error("Proxy error:", err.message);
    res.status(502).json({
      detail: err.message || "Backend request failed. Check EXTRACT_API_URL and that the backend is running.",
    });
  }
};
