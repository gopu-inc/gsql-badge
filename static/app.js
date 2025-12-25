function upload() {
  const fileInput = document.getElementById("file")
  const result = document.getElementById("result")

  if (!fileInput.files.length) {
    result.innerText = "❌ Sélectionne une image"
    return
  }

  const form = new FormData()
  form.append("file", fileInput.files[0])

  result.innerText = "⏳ Génération du badge..."

  fetch("/upload", {
    method: "POST",
    body: form
  })
    .then(res => res.json())
    .then(data => {
      const url = location.origin + data.badge_url
      result.innerHTML = `
        ✅ Badge prêt :
        <br>
        <a href="${url}" target="_blank">${url}</a>
        <pre class="code">![Badge](${url})</pre>
      `
    })
    .catch(() => {
      result.innerText = "❌ Erreur lors de la génération"
    })
}
