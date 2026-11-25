const token = location.hash.slice(1);
history.replaceState(null, "", location.pathname);
const button = document.getElementById("action-confirm");
const title = document.getElementById("action-title");
const status = document.getElementById("action-message");

async function request(operation) {
  const response = await fetch(`/api/reminders/${operation}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Hearth could not update this reminder.");
  return result;
}

function completed(result) {
  button.hidden = true;
  status.textContent = `${result.label}. This reminder link has been used.`;
}

button.addEventListener("click", async () => {
  button.disabled = true;
  try {
    completed(await request("action"));
  } catch (error) {
    status.textContent = error.message;
    button.disabled = false;
  }
});

try {
  const result = await request("inspect");
  if (result.applied) completed(result);
  else {
    title.textContent = result.title;
    status.textContent = "Confirm this change to your reminder.";
    button.textContent = result.label;
    button.hidden = false;
  }
} catch (error) {
  status.textContent = error.message;
}
