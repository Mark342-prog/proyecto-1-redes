const chat = document.getElementById("chat");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");
const resetBtn = document.getElementById("reset-btn");
const sendBtn = form.querySelector(".composer__send");

let sessionId = localStorage.getItem("pharmacy-session-id") || null;

function guardarSesion(id) {
  sessionId = id;
  localStorage.setItem("pharmacy-session-id", id);
}

function agregarMensaje(texto, tipo) {
  const fila = document.createElement("div");
  fila.className = `msg msg--${tipo}`;
  const burbuja = document.createElement("div");
  burbuja.className = "msg__bubble";
  burbuja.textContent = texto;
  fila.appendChild(burbuja);
  chat.appendChild(fila);
  chat.scrollTop = chat.scrollHeight;
  return fila;
}

async function enviarMensaje(mensaje) {
  const respuesta = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: mensaje, sessionId })
  });
  const datos = await respuesta.json();
  if (!respuesta.ok) {
    throw new Error(datos.error || "Ocurrió un error inesperado.");
  }
  return datos;
}

form.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const mensaje = input.value.trim();
  if (!mensaje) return;

  agregarMensaje(mensaje, "user");
  input.value = "";
  input.disabled = true;
  sendBtn.disabled = true;
  const pendiente = agregarMensaje("Pensando...", "bot");
  pendiente.classList.add("msg--pending");

  try {
    const datos = await enviarMensaje(mensaje);
    if (datos.sessionId) guardarSesion(datos.sessionId);
    pendiente.remove();
    agregarMensaje(datos.answer, "bot");
  } catch (error) {
    pendiente.remove();
    agregarMensaje(error.message, "error");
  } finally {
    input.disabled = false;
    sendBtn.disabled = false;
    input.focus();
  }
});

resetBtn.addEventListener("click", async () => {
  try {
    await fetch("/api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId })
    });
  } catch (error) {
    // Si falla el reset en el servidor, igual limpiamos la vista localmente.
  }
  chat.innerHTML = "";
  agregarMensaje("Contexto limpiado. ¿En qué puedo ayudarte?", "bot");
});
