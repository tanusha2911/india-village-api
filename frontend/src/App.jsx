import { useEffect, useState } from "react";
import axios from "axios";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import "./App.css";
import Login from "./Login";

const API_URL = "https://india-village-api-r66o.onrender.com";

function App() {
  const [states, setStates] = useState([]);
  const [districts, setDistricts] = useState([]);
  const [subdistricts, setSubdistricts] = useState([]);
  const [villages, setVillages] = useState([]);

  const [selectedState, setSelectedState] = useState("");
  const [selectedDistrict, setSelectedDistrict] = useState("");
  const [selectedSubdistrict, setSelectedSubdistrict] = useState("");

  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState([]);

  const [error, setError] = useState("");
  const [dashboard, setDashboard] = useState(null);
  const [usage, setUsage] = useState(null);
  const [chartData, setChartData] = useState([]);
  const [adminAnalytics, setAdminAnalytics] = useState(null);
  const [topStates, setTopStates] = useState([]);
  const [requestTrend, setRequestTrend] = useState([]);
  const [responseTimeTrend, setResponseTimeTrend] = useState([]);
  const [endpointAnalytics, setEndpointAnalytics] = useState([]);
  const [hourlyUsage, setHourlyUsage] = useState([]);
  const [adminUsers, setAdminUsers] = useState([]);
  const [userSearch, setUserSearch] = useState("");
  const [userPlanFilter, setUserPlanFilter] = useState("ALL");
  const [userRoleFilter, setUserRoleFilter] = useState("ALL");
  const [userSort, setUserSort] = useState("id_desc");
  const [selectedUser, setSelectedUser] = useState(null);
  const [selectedUserIds, setSelectedUserIds] = useState([]);
  const [bulkPlan, setBulkPlan] = useState("PREMIUM");
  const [isAuthenticated, setIsAuthenticated] = useState(
    () => Boolean(localStorage.getItem("access_token"))
  );


  // Get JWT token
  const token = localStorage.getItem("access_token");
  const authHeaders = token && token !== "null" && token !== "undefined"
    ? {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
    : {};

  // Load data after successful login
  useEffect(() => {
    if (!isAuthenticated) return;
    
    fetchStates();
    fetchDashboard();
    fetchAdminAnalytics();
    fetchTopStates();
    fetchRequestTrend();
    fetchResponseTimeTrend();
    fetchEndpointAnalytics();
    fetchHourlyUsage();
    fetchAdminUsers();
    fetchUsage();
  }, [isAuthenticated]);

  // Load states
  const fetchStates = async () => {
    try {
      setError("");

      const response = await axios.get(
        `${API_URL}/api/states`,
        authHeaders
      );

      setStates(response.data.data);
    } catch (err) {
      console.error(err);
      setError("Failed to load states.");
    }
  };

  // Load dashboard
  const fetchDashboard = async () => {
    try {
      const response = await axios.get(
        `${API_URL}/dashboard/me`,
        authHeaders
      );

      setDashboard(response.data);
    } catch (err) {
      console.error(err);
    }
  };

  // Load API usage
  const fetchUsage = async () => {
    try {
      const response = await axios.get(
        `${API_URL}/dashboard/usage`,
        authHeaders
      );

      setUsage(response.data);

      setChartData([
        {
          name: "Total Requests",
          requests: response.data.summary.total_requests,
        },
        {
          name: "Avg Response Time",
          requests: response.data.summary.average_response_time,
        },
      ]);
    } catch (err) {
      console.error(err);
    }
  };

  // Load Admin Analytics
  const fetchAdminAnalytics = async () => {
    try {
      const response = await axios.get(
        `${API_URL}/admin/analytics`,
        authHeaders
      );

      setAdminAnalytics(response.data.analytics);
    } catch (err) {
      console.error("Admin analytics error:", err);
    }
  };

  const fetchTopStates = async () => {
    try {
      const response = await axios.get(
        `${API_URL}/admin/analytics/states`,
        authHeaders
      );

      setTopStates(response.data.states);
    } catch (err) {
      console.error("Top states analytics error:", err);
    }
  };

  const fetchRequestTrend = async () => {
    try {
      const response = await axios.get(
        `${API_URL}/admin/analytics/requests`,
        authHeaders
      );

      setRequestTrend(response.data.requests);
    } catch (err) {
      console.error("Request trend analytics error:", err);
    }
  };

  const fetchResponseTimeTrend = async () => {
    try {
      const response = await axios.get(
        `${API_URL}/admin/analytics/response-time`,
        authHeaders
      );

      setResponseTimeTrend(response.data.response_times);
    } catch (err) {
      console.error("Response time analytics error:", err);
    }
  };

  const fetchEndpointAnalytics = async () => {
    try {
      const response = await axios.get(
        `${API_URL}/admin/analytics/endpoints`,
        authHeaders
      );

      setEndpointAnalytics(response.data.endpoints);
    } catch (err) {
      console.error("Endpoint analytics error:", err);
    }
  };

  const fetchHourlyUsage = async () => {
    try {
      const response = await axios.get(
        `${API_URL}/admin/analytics/hourly`,
        authHeaders
      );
      setHourlyUsage(response.data.hourly_usage);
    } catch (err) {
      console.error("Hourly usage analytics error:", err);
    }
  };

  const fetchAdminUsers = async () => {
    try {
      const response = await axios.get(
        `${API_URL}/admin/users`,
        authHeaders
      );
      setAdminUsers(response.data.users);
    } catch (err) {
      console.error("Admin users error:", err);
    }
  };

  // State changed
  const handleStateChange = async (e) => {
    const stateCode = e.target.value;

    setSelectedState(stateCode);
    setSelectedDistrict("");
    setSelectedSubdistrict("");

    setDistricts([]);
    setSubdistricts([]);
    setVillages([]);

    if (!stateCode) return;

    try {
      setError("");

      const response = await axios.get(
        `${API_URL}/api/states/${stateCode}/districts`,
        authHeaders
      );

      setDistricts(response.data.data);
    } catch (err) {
      console.error(err);
      setError("Failed to load districts.");
    }
  };

  // District changed
  const handleDistrictChange = async (e) => {
    const districtCode = e.target.value;

    setSelectedDistrict(districtCode);
    setSelectedSubdistrict("");

    setSubdistricts([]);
    setVillages([]);

    if (!districtCode) return;

    try {
      setError("");

      const response = await axios.get(
        `${API_URL}/api/districts/${districtCode}/subdistricts`,
        authHeaders
      );

      setSubdistricts(response.data.data);
    } catch (err) {
      console.error(err);
      setError("Failed to load sub-districts.");
    }
  };

  // Sub-district changed
  const handleSubdistrictChange = async (e) => {
    const subdistrictCode = e.target.value;

    setSelectedSubdistrict(subdistrictCode);
    setVillages([]);

    if (!subdistrictCode) return;

    try {
      setError("");

      const response = await axios.get(
        `${API_URL}/api/subdistricts/${subdistrictCode}/villages`,
        authHeaders
      );

      setVillages(response.data.data);
    } catch (err) {
      console.error(err);
      setError("Failed to load villages.");
    }
  };

  // Village search
  const handleSearch = async (e) => {
    const value = e.target.value;

    setSearch(value);

    if (value.trim().length < 2) {
      setSearchResults([]);
      return;
    }

    try {
      setError("");

      const response = await axios.get(
        `${API_URL}/api/villages/search`,
        {
          ...authHeaders,
          params: {
            q: value,
            page: 1,
            limit: 10,
          },
        }
      );

      setSearchResults(response.data.data);
    } catch (err) {
      console.error(err);
      setError("Village search failed.");
    }
  };

  if (!isAuthenticated) {
    return (
      <Login
        onLoginSuccess={() => setIsAuthenticated(true)}
        />
    );
  }
  
  return (
    <div className="container">

      <button
        onClick={() => {
          localStorage.removeItem("access_token");
          setIsAuthenticated(false);
        }}
        >
        Logout
      </button>

      {/* Dashboard */}
      {dashboard && (
        <div className="card">
          <h2>Dashboard</h2>

          <p>
            <strong>Email:</strong>{" "}
            {dashboard.user.email}
          </p>

          <p>
            <strong>Plan:</strong>{" "}
            {dashboard.user.plan}
          </p>

          <p>
            <strong>Today's Requests:</strong>{" "}
            {dashboard.usage.today}
          </p>

          <p>
            <strong>Daily Limit:</strong>{" "}
            {dashboard.usage.daily_limit}
          </p>

          <p>
            <strong>Remaining Requests:</strong>{" "}
            {dashboard.usage.remaining}
          </p>
        </div>
      )}

      {/* API Usage */}
      {usage && (
        <div className="card">
          <h2>API Usage</h2>

          <p>
            <strong>Total Requests:</strong>{" "}
            {usage.summary.total_requests}
          </p>

          <p>
            <strong>Average Response Time:</strong>{" "}
            {usage.summary.average_response_time} ms
          </p>

          <h3>Recent Requests</h3>

          {usage.recent_requests.map((request, index) => (
            <p key={index}>
              {request.method} {request.endpoint} —{" "}
              {request.status_code} —{" "}
              {request.response_time} ms
            </p>
          ))}

          <h3>API Analytics</h3>

          <div style={{ width: "100%", height: 300 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="requests" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ADMIN ANALYTICS */}

      {dashboard?.user?.role === "ADMIN" && adminAnalytics && (
        <section className="section">
          <h2>Admin Analytics</h2>

          <div className="dashboard-cards">
            
            <div className="card">
              <h3>Total Users</h3>
              <p>{adminAnalytics.total_users}</p>
            </div>

            <div className="card">
              <h3>Total API Requests</h3>
              <p>{adminAnalytics.total_requests}</p>
            </div>

            <div className="card">
              <h3>Average Response Time</h3>
              <p>{adminAnalytics.average_response_time} ms</p>
            </div>
            
          </div>

          <h3>Users by Plan</h3>

          <div className="plan-list">
            {adminAnalytics.users_by_plan.map((item) => (
              <div
              className="plan-item"
              key={item.plan}
            >
              <span>{item.plan}</span>
              <strong>{item.users}</strong>
            </div>
          ))}
        </div>

        <h3>Top 10 States by Village Count</h3>

        <div style={{ width: "100%", height: 400 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={topStates}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="state" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="villages" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        
      </section>
    )}

    <h3>API Requests - Last 30 Days</h3>

    <div style={{ width: "100%", height: 400 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={requestTrend}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Line
            type="monotone"
            dataKey="requests"
            stroke="#8884d8"
            strokeWidth={2}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>

    <h3>Response Time Trends (p95 / p99)</h3>

    <div style={{ width: "100%", height: 400 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={responseTimeTrend}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Line
            type="monotone"
            dataKey="p95"
            name="p95"
            stroke="#8884d8"
            strokeWidth={2}
          />
          <Line
            type="monotone"
            dataKey="p99"
            name="p99"
            stroke="#82ca9d"
            strokeWidth={2}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>

    <h3>Requests by Endpoint</h3>

    <div style={{ width: "100%", height: 400 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={endpointAnalytics}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="endpoint" />
          <YAxis />
          <Tooltip />
          <Bar dataKey="requests" />
        </BarChart>
      </ResponsiveContainer>
    </div>

    <h3>API Usage by Hour</h3>

    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(6, 1fr)",
        gap: "12px",
        marginTop: "15px",
      }}
    >
      {Array.from({ length: 24 }, (_, hour) => {
        const item = hourlyUsage.find((data) => data.hour === hour);
        const requests = item ? item.requests : 0;

        const maxRequests = Math.max(
          ...hourlyUsage.map((data) => data.requests),
          1
        );

        const intensity = requests / maxRequests;

        return (
          <div
            key={hour}
            title={`${requests} requests at ${hour}:00`}
            style={{
              padding: "18px 10px",
              borderRadius: "8px",
              textAlign: "center",
              backgroundColor: `rgba(136, 132, 216, ${
                requests === 0 ? 0.08 : 0.2 + intensity * 0.8
              })`,
              border: "1px solid #ddd",
            }}
          >
            <div style={{ fontWeight: "bold" }}>
              {hour}:00
            </div>

            <div style={{ marginTop: "8px" }}>
              {requests} requests
            </div>
          </div>
        );
      })}
    </div>

    {selectedUser && (
      <div className="card" style={{ marginTop: "20px" }}>
        <h3>User Details</h3>

        <p>
          <strong>ID:</strong> {selectedUser.id}
        </p>

        <p>
          <strong>Name:</strong> {selectedUser.name}
        </p>

        <p>
          <strong>Email:</strong> {selectedUser.email}
        </p>

        <p>
          <strong>Plan:</strong> {selectedUser.plan}
        </p>

        <p>
          <strong>Role:</strong>{" "}
          <select
            value={selectedUser.role}
            onChange={async (e) => {
              const newRole = e.target.value;

              try {
                await axios.put(
                `${API_URL}/admin/users/${selectedUser.id}/role`,
                null,
                {
                  ...authHeaders,
                  params: {
                    role: newRole,
                  },
                }
              );

              setSelectedUser({
                ...selectedUser,
                role: newRole,
              });

              fetchAdminUsers();
            } catch (err) {
              console.error("Role update error:", err);

              alert(
                err.response?.data?.detail ||
                "Failed to update user role"
              );
            }
          }}
        >
          <option value="USER">USER</option>
          <option value="ADMIN">ADMIN</option>
        </select>
      </p>

        <p>
          <strong>Created Date:</strong>{" "}
          {new Date(selectedUser.created_at).toLocaleDateString()}
        </p>

        <button
          onClick={() => setSelectedUser(null)}
          style={{ marginTop: "10px" }}
        >
          Close
        </button>

        <button
          onClick={async () => {
            const confirmed = window.confirm(
              `Are you sure you want to delete user ${selectedUser.name}?`
            );
            
            if (!confirmed) return;

            try {
              await axios.delete(
                `${API_URL}/admin/users/${selectedUser.id}`,
                authHeaders
              );

              alert("User deleted successfully");

              setSelectedUser(null);
              setSelectedUserIds(
                selectedUserIds.filter((id) => id !== selectedUser.id)
              );

              fetchAdminUsers();
              fetchAdminAnalytics();
            } catch (err) {
              console.error("Delete user error:", err);

              alert(
                err.response?.data?.detail ||
                "Failed to delete user"
              );
            }
          }}
          style={{
            marginTop: "10px",
            marginLeft: "10px"
          }}
        >
          Delete User
        </button>
      </div>
    )}

    <h3>User Management</h3>

    <div style={{ marginBottom: "15px" }}>
      <select
        value={bulkPlan}
        onChange={(e) => setBulkPlan(e.target.value)}
      >
        <option value="PREMIUM">PREMIUM</option>
        <option value="FREE">FREE</option>
      </select>

      <button
        style={{ marginLeft: "10px" }}
        onClick={async () => {
          if (selectedUserIds.length === 0) {
            alert("Please select at least one user");
            return;
          }

          try {
            const response = await axios.put(
              `${API_URL}/admin/users/bulk-plan`,
              selectedUserIds,
              {
                ...authHeaders,
                params: {
                  plan: bulkPlan,
                },
              }
            );

            alert(
              `${response.data.updated_count} user(s) updated to ${bulkPlan}`
            );

            fetchAdminUsers();
          } catch (err) {
            console.error(
              "Bulk plan update error:",
              JSON.stringify(err.response?.data, null, 2)
            );

            alert(
              err.response?.data?.detail ||
              "Failed to update user plans"
            );
          }
        }}
      > 
        Update Plan
      </button>
  </div>

    <input
      type="text"
      placeholder="Search by name or email"
      value={userSearch}
      onChange={(e) => setUserSearch(e.target.value)}
    />

    <select
    value={userPlanFilter}
    onChange={(e) => setUserPlanFilter(e.target.value)}
    >
      <option value="ALL">All Plans</option>
      <option value="FREE">FREE</option>
      <option value="PREMIUM">PREMIUM</option>
    </select>

    <select
      value={userRoleFilter}
      onChange={(e) => setUserRoleFilter(e.target.value)}
    >
      <option value="ALL">All Roles</option>
      <option value="USER">USER</option>
      <option value="ADMIN">ADMIN</option>
    </select>

    <select
      value={userSort}
      onChange={(e) => setUserSort(e.target.value)}
    >
      <option value="id_desc">Newest ID</option>
      <option value="id_asc">Oldest ID</option>
      <option value="name_asc">Name A-Z</option>
      <option value="name_desc">Name Z-A</option>
      <option value="plan_asc">Plan A-Z</option>
      <option value="role_asc">Role A-Z</option>
      <option value="created_desc">Newest Created</option>
      <option value="created_asc">Oldest Created</option>
    </select>

    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>
              <input
                type="checkbox"
                onChange={(e) => {
                  if (e.target.checked) {
                    setSelectedUserIds(
                      adminUsers.map((user) => user.id)
                    );
                  } else {
                    setSelectedUserIds([]);
                  }
                }}
              />
            </th>

            <th>ID</th>
            <th>Name</th>
            <th>Email</th>
            <th>Plan</th>
            <th>Role</th>
            <th>Created Date</th>
          </tr>
        </thead>

        <tbody>
          {adminUsers
            .filter( 
              (user) =>
                (user.name.toLowerCase().includes(userSearch.toLowerCase()) ||
                  user.email.toLowerCase().includes(userSearch.toLowerCase())) &&
                (userPlanFilter === "ALL" || user.plan === userPlanFilter) &&
                (userRoleFilter === "ALL" || user.role === userRoleFilter)
            )
            .sort((a, b) => {
              switch (userSort) {
                case "id_asc":
                  return a.id - b.id;

                case "id_desc":
                  return b.id - a.id;

                case "name_asc":
                  return a.name.localeCompare(b.name);

                case "name_desc":
                  return b.name.localeCompare(a.name);

                case "plan_asc":
                  return a.plan.localeCompare(b.plan);

                case "role_asc":
                  return a.role.localeCompare(b.role);

                case "created_desc":
                  return new Date(b.created_at) - new Date(a.created_at);

                case "created_asc":
                  return new Date(a.created_at) - new Date(b.created_at);

                default:
                  return b.id - a.id;
              }
            })
            
            .map((user) => (
              <tr
                key={user.id}
                onClick={() => setSelectedUser(user)}
                style={{ cursor: "pointer" }}
              >
                <td>
                  <input
                    type="checkbox"
                    checked={selectedUserIds.includes(user.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedUserIds([
                          ...selectedUserIds,
                          user.id,
                        ]);
                      } else {
                        setSelectedUserIds(
                          selectedUserIds.filter((id) => id !== user.id)
                        );
                      }
                    }}
                  />
                </td>

                <td>
                  <button onClick={(e) => {
                    e.stopPropagation();
                    setSelectedUser(user);
                  }}>
                    View
                  </button>
                </td>

                <td>{user.id}</td>
                <td>{user.name}</td>
                <td>{user.email}</td>
                <td>{user.plan}</td>
                <td>{user.role}</td>
                <td>
                  {new Date(user.created_at).toLocaleDateString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Main heading */}
      <h1>🇮🇳 India Village API</h1>

      <p className="subtitle">
        Explore Indian geographical data from State to Village
      </p>

      {/* Error */}
      {error && (
        <div className="error">
          {error}
        </div>
      )}

      {/* Location Explorer */}
      <div className="card">
        <h2>Location Explorer</h2>

        {/* State */}
        <label>State</label>

        <select
          value={selectedState}
          onChange={handleStateChange}
        >
          <option value="">
            Select State
          </option>

          {states.map((state) => (
            <option
              key={state.state_code}
              value={state.state_code}
            >
              {state.state_name}
            </option>
          ))}
        </select>

        {/* District */}
        <label>District</label>

        <select
          value={selectedDistrict}
          onChange={handleDistrictChange}
          disabled={!selectedState}
        >
          <option value="">
            Select District
          </option>

          {districts.map((district) => (
            <option
              key={district.district_code}
              value={district.district_code}
            >
              {district.district_name}
            </option>
          ))}
        </select>

        {/* Sub-district */}
        <label>Sub-District</label>

        <select
          value={selectedSubdistrict}
          onChange={handleSubdistrictChange}
          disabled={!selectedDistrict}
        >
          <option value="">
            Select Sub-District
          </option>

          {subdistricts.map((subdistrict) => (
            <option
              key={subdistrict.subdistrict_code}
              value={subdistrict.subdistrict_code}
            >
              {subdistrict.subdistrict_name}
            </option>
          ))}
        </select>

        {/* Villages */}
        <label>Villages</label>

        <select
          disabled={!selectedSubdistrict}
        >
          <option value="">
            {villages.length > 0
              ? `${villages.length} villages found`
              : "Select Village"}
          </option>

          {villages.map((village) => (
            <option
              key={village.place_code}
              value={village.place_code}
            >
              {village.village_name}
            </option>
          ))}
        </select>
      </div>

      {/* Search */}
      <div className="card">
        <h2>Search Villages</h2>

        <input
          type="text"
          placeholder="Search village name..."
          value={search}
          onChange={handleSearch}
        />

        {searchResults.length > 0 && (
          <div className="results">
            {searchResults.map((result) => (
              <div
                className="result"
                key={`${result.place_code}-${result.village_name}`}
              >
                <strong>
                  {result.village_name}
                </strong>

                <span>
                  {result.subdistrict_name},{" "}
                  {result.district_name},{" "}
                  {result.state_name}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

    </div>
  );
}

export default App;
