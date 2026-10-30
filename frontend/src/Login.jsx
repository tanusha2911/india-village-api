
import { useState } from "react";
import axios from "axios";

function Login({ onLoginSuccess }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const response = await axios.post(
        "https://india-village-api-r66o.onrender.com/auth/login",
        {
          email: email,
          password: password,
        }
      );

      const token = response.data.access_token;

      if (!token) {
        throw new Error("Access token not received");
      }

      localStorage.setItem("access_token", token);

      onLoginSuccess();
    } catch (err) {
      console.error("Login error:", err);
      setError(
        err.response?.data?.detail || "Login failed. Check your credentials."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        maxWidth: "400px",
        margin: "100px auto",
        padding: "30px",
        border: "1px solid #ddd",
        borderRadius: "12px",
      }}
    >
      <h2>India Village Login</h2>

      <form onSubmit={handleLogin}>
        <input
          type="email"
          placeholder="Enter email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          style={{ width: "100%", padding: "12px", marginBottom: "15px" }}
        />

        <input
          type="password"
          placeholder="Enter password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          style={{ width: "100%", padding: "12px", marginBottom: "15px" }}
        />

        <button
          type="submit"
          disabled={loading}
          style={{ width: "100%", padding: "12px" }}
        >
          {loading ? "Logging in..." : "Login"}
        </button>
      </form>

      {error && (
        <p style={{ color: "red", marginTop: "15px" }}>{error}</p>
      )}
    </div>
  );
}

export default Login;
