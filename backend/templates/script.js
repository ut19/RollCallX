const BACKEND = "http://127.0.0.1:5000";

// REGISTER
async function register() {
  const name = document.getElementById("reg_name").value;
  const email = document.getElementById("reg_email").value;
  const password = document.getElementById("reg_password").value;

  const res = await fetch(`${BACKEND}/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, email, password }),
  });

  const data = await res.json();
  alert(data.status === "success" ? "Registered!" : data.message);
}

// LOGIN
async function login() {
  const email = document.getElementById("login_email").value;
  const password = document.getElementById("login_password").value;

  const res = await fetch(`${BACKEND}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (res.ok) {
    window.location.href = "dashboard.html";
  } else {
    alert("Login failed");
  }
}

// JOIN CLASSROOM
async function joinClass() {
  const email = document.getElementById("email").value;
  const class_code = document.getElementById("class_code").value;

  const res = await fetch(`${BACKEND}/join_classroom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, class_code }),
  });

  const data = await res.json();
  document.getElementById("result").innerText = data.message || "Joined class!";
}

// MARK ATTENDANCE
async function markAttendance() {
  const email = document.getElementById("email").value;
  const class_code = document.getElementById("class_code").value;
  const session_code = document.getElementById("session_code").value;

  if (!navigator.geolocation) {
    alert("Geolocation is not supported.");
    return;
  }

  navigator.geolocation.getCurrentPosition(async (pos) => {
    const lat = pos.coords.latitude;
    const lon = pos.coords.longitude;

    const res = await fetch(`${BACKEND}/mark_attendance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        class_code,
        session_code,
        latitude: lat,
        longitude: lon,
      }),
    });

    const data = await res.json();
    document.getElementById("result").innerText = data.message;
  });
}
