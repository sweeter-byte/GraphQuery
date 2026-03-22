#include "DataStructure/Graph.h"
#include <chrono>
#include <algorithm>
#include <atomic>
#include "Base/Timer.h"
#include <omp.h>
#include <tbb/concurrent_queue.h>

namespace GraphLib
{
    void Graph::EnumerateLocalTriangles()
    {
        Timer Trianglestimer;
        Trianglestimer.Start();

        local_triangles.resize(GetNumEdges());
        std::vector<int> vertices_sorted_by_degree(GetNumVertices(), -1);
        std::iota(vertices_sorted_by_degree.begin(), vertices_sorted_by_degree.end(), 0);
        std::sort(vertices_sorted_by_degree.begin(), vertices_sorted_by_degree.end(),
                  [&](int a, int b)
                  { return GetDegree(a) > GetDegree(b); });
        std::vector<std::vector<int>> inc_edge_list(GetNumVertices(), std::vector<int>());
        std::vector<int> edge_inv_idx_from(GetNumEdges(), -1);
        std::vector<int> nbr_edge_id(GetNumVertices(), -1);
        for (int i = 0; i < GetNumVertices(); i++)
        {
            for (int e : GetAllIncidentEdges(i))
            {
                edge_inv_idx_from[e] = inc_edge_list[i].size();
                inc_edge_list[i].emplace_back(e);
            }
        }
        unsigned long long num_triangles = 0;
        for (int i = 0; i < GetNumVertices() - 2; i++)
        {
            int u = vertices_sorted_by_degree[i];
            for (int e : inc_edge_list[u])
            {
                nbr_edge_id[GetOppositePoint(e)] = e;
            }
            for (int e : inc_edge_list[u])
            {
                int v = GetOppositePoint(e), oe = GetOppositeEdge(e);
                for (int eprime : GetAllIncidentEdges(v))
                {
                    int w = GetOppositePoint(eprime);
                    if (nbr_edge_id[w] != -1)
                    {
                        local_triangles[e].emplace_back(std::tuple(w, nbr_edge_id[w], eprime));
                        local_triangles[oe].emplace_back(std::tuple(w, eprime, nbr_edge_id[w]));
                        num_triangles += 2;
                        if (e > nbr_edge_id[w])
                        {
                            local_triangles[eprime].emplace_back(std::tuple(u, oe, GetOppositeEdge(nbr_edge_id[w])));
                            local_triangles[GetOppositeEdge(eprime)].emplace_back(std::tuple(u, GetOppositeEdge(nbr_edge_id[w]), oe));
                            num_triangles += 2;
                        }
                    }
                }
            }
            for (int e : inc_edge_list[u])
            {
                int v = GetOppositePoint(e), oe = GetOppositeEdge(e);
                nbr_edge_id[v] = -1;
                int oe_idx_from_v = edge_inv_idx_from[oe];
                if (inc_edge_list[v].size() == 1)
                {
                    inc_edge_list[v].pop_back();
                }
                else
                {
                    int v_inc_last = inc_edge_list[v].back();
                    std::swap(inc_edge_list[v][inc_edge_list[v].size() - 1], inc_edge_list[v][oe_idx_from_v]);
                    edge_inv_idx_from[v_inc_last] = oe_idx_from_v;
                    edge_inv_idx_from[oe] = -1;
                    inc_edge_list[v].pop_back();
                }
            }
        }
        Trianglestimer.Stop();
        std::cout << "[Perf] EnumerateLocalTriangles completed. " << " NUM_Triangles: " << num_triangles << " Time: " << Trianglestimer.GetTime() << "ms" << std::endl;
    }

    void Graph::query_EnumerateLocalFourCycles()
    {
        Timer timer;
        timer.Start();

        local_four_cycles.resize(GetNumEdges());
        double total_required = 0, done = 0;
        for (int i = 0; i < GetNumEdges(); i++)
        {
            auto &[u, v] = edge_list[i];
            total_required += GetDegree(u) * GetDegree(v);
        }
        long long num_four_cycles = 0;
        for (int i = 0; i < GetNumEdges(); i++)
        {
            auto &[u, v] = edge_list[i];
            if (GetDegree(u) < GetDegree(v))
            {
                for (int &fourth_edge_opp : GetAllIncidentEdges(u))
                {
                    int fourth_vertex = GetOppositePoint(fourth_edge_opp);
                    if (fourth_vertex == v)
                        continue;
                    if (GetDegree(fourth_vertex) < GetDegree(v))
                    {
                        for (int &third_edge_opp : GetAllIncidentEdges(fourth_vertex))
                        {
                            int third_vertex = GetOppositePoint(third_edge_opp);
                            if (third_vertex == u)
                                continue;
                            int snd_edge = GetEdgeIndex(v, third_vertex);
                            if (snd_edge != -1)
                            {
                                int fourth_edge = fourth_edge_opp ^ 1;
                                int third_edge = third_edge_opp ^ 1;
                                int fst_diag = GetEdgeIndex(u, third_vertex);
                                int snd_diag = GetEdgeIndex(v, fourth_vertex);
                                local_four_cycles[i].emplace_back(FourMotif(
                                    {i, snd_edge, third_edge, fourth_edge},
                                    {fst_diag, snd_diag}));
                                num_four_cycles++;
                            }
                        }
                    }
                    else
                    {
                        for (int &snd_edge : GetAllIncidentEdges(v))
                        {
                            int third_vertex = GetOppositePoint(snd_edge);
                            if (third_vertex == u)
                                continue;
                            int third_edge = GetEdgeIndex(third_vertex, fourth_vertex);
                            if (third_edge != -1)
                            {
                                int fourth_edge = fourth_edge_opp ^ 1;
                                int fst_diag = GetEdgeIndex(u, third_vertex);
                                int snd_diag = GetEdgeIndex(v, fourth_vertex);
                                local_four_cycles[i].emplace_back(FourMotif(
                                    {i, snd_edge, third_edge, fourth_edge},
                                    {fst_diag, snd_diag}));
                                num_four_cycles++;
                            }
                        }
                    }
                }
            }
            else
            {
                for (int &snd_edge : GetAllIncidentEdges(v))
                {
                    int third_vertex = GetOppositePoint(snd_edge);
                    if (third_vertex == u)
                        continue;
                    if (GetDegree(third_vertex) < GetDegree(u))
                    {
                        for (int &third_edge : GetAllIncidentEdges(third_vertex))
                        {
                            int fourth_vertex = GetOppositePoint(third_edge);
                            if (fourth_vertex == v)
                                continue;
                            int fourth_edge = GetEdgeIndex(fourth_vertex, u);
                            if (fourth_edge != -1)
                            {
                                int fst_diag = GetEdgeIndex(u, third_vertex);
                                int snd_diag = GetEdgeIndex(v, fourth_vertex);
                                local_four_cycles[i].emplace_back(FourMotif(
                                    {i, snd_edge, third_edge, fourth_edge},
                                    {fst_diag, snd_diag}));
                                num_four_cycles++;
                            }
                        }
                    }
                    else
                    {
                        for (int &fourth_edge_opp : GetAllIncidentEdges(u))
                        {
                            int fourth_vertex = GetOppositePoint(fourth_edge_opp);
                            if (fourth_vertex == v)
                                continue;
                            int third_edge = GetEdgeIndex(third_vertex, fourth_vertex);
                            if (third_edge != -1)
                            {
                                int fourth_edge = fourth_edge_opp ^ 1;
                                int fst_diag = GetEdgeIndex(u, third_vertex);
                                int snd_diag = GetEdgeIndex(v, fourth_vertex);
                                local_four_cycles[i].emplace_back(FourMotif(
                                    {i, snd_edge, third_edge, fourth_edge},
                                    {fst_diag, snd_diag}));
                                num_four_cycles++;
                            }
                        }
                    }
                }
            }
            done += GetDegree(u) * GetDegree(v);
        }
        timer.Stop();
        std::cout << "[Perf] EnumerateLocalFourCycles completed. "
                  << "Cycles: " << num_four_cycles << ", "
                  << "Time: " << timer.GetTime() << "ms"
                  << std::endl;
    }

#ifdef SERIAL_VERSION
    void Graph::query_EnumerateLocalFourCycles()
    {
        Timer timer;
        timer.Start();

        local_four_cycles.resize(GetNumEdges());
        double total_required = 0, done = 0;
        for (int i = 0; i < GetNumEdges(); i++)
        {
            auto &[u, v] = edge_list[i];
            total_required += GetDegree(u) * GetDegree(v);
        }
        long long num_four_cycles = 0;
        for (int i = 0; i < GetNumEdges(); i++)
        {
            auto &[u, v] = edge_list[i];
            if (GetDegree(u) < GetDegree(v))
            {
                for (int &fourth_edge_opp : GetAllIncidentEdges(u))
                {
                    int fourth_vertex = GetOppositePoint(fourth_edge_opp);
                    if (fourth_vertex == v)
                        continue;
                    if (GetDegree(fourth_vertex) < GetDegree(v))
                    {
                        for (int &third_edge_opp : GetAllIncidentEdges(fourth_vertex))
                        {
                            int third_vertex = GetOppositePoint(third_edge_opp);
                            if (third_vertex == u)
                                continue;
                            int snd_edge = GetEdgeIndex(v, third_vertex);
                            if (snd_edge != -1)
                            {
                                int fourth_edge = fourth_edge_opp ^ 1;
                                int third_edge = third_edge_opp ^ 1;
                                int fst_diag = GetEdgeIndex(u, third_vertex);
                                int snd_diag = GetEdgeIndex(v, fourth_vertex);
                                local_four_cycles[i].emplace_back(FourMotif(
                                    {i, snd_edge, third_edge, fourth_edge},
                                    {fst_diag, snd_diag}));
                                num_four_cycles++;
                            }
                        }
                    }
                    else
                    {
                        for (int &snd_edge : GetAllIncidentEdges(v))
                        {
                            int third_vertex = GetOppositePoint(snd_edge);
                            if (third_vertex == u)
                                continue;
                            int third_edge = GetEdgeIndex(third_vertex, fourth_vertex);
                            if (third_edge != -1)
                            {
                                int fourth_edge = fourth_edge_opp ^ 1;
                                int fst_diag = GetEdgeIndex(u, third_vertex);
                                int snd_diag = GetEdgeIndex(v, fourth_vertex);
                                local_four_cycles[i].emplace_back(FourMotif(
                                    {i, snd_edge, third_edge, fourth_edge},
                                    {fst_diag, snd_diag}));
                                num_four_cycles++;
                            }
                        }
                    }
                }
            }
            else
            {
                for (int &snd_edge : GetAllIncidentEdges(v))
                {
                    int third_vertex = GetOppositePoint(snd_edge);
                    if (third_vertex == u)
                        continue;
                    if (GetDegree(third_vertex) < GetDegree(u))
                    {
                        for (int &third_edge : GetAllIncidentEdges(third_vertex))
                        {
                            int fourth_vertex = GetOppositePoint(third_edge);
                            if (fourth_vertex == v)
                                continue;
                            int fourth_edge = GetEdgeIndex(fourth_vertex, u);
                            if (fourth_edge != -1)
                            {
                                int fst_diag = GetEdgeIndex(u, third_vertex);
                                int snd_diag = GetEdgeIndex(v, fourth_vertex);
                                local_four_cycles[i].emplace_back(FourMotif(
                                    {i, snd_edge, third_edge, fourth_edge},
                                    {fst_diag, snd_diag}));
                                num_four_cycles++;
                            }
                        }
                    }
                    else
                    {
                        for (int &fourth_edge_opp : GetAllIncidentEdges(u))
                        {
                            int fourth_vertex = GetOppositePoint(fourth_edge_opp);
                            if (fourth_vertex == v)
                                continue;
                            int third_edge = GetEdgeIndex(third_vertex, fourth_vertex);
                            if (third_edge != -1)
                            {
                                int fourth_edge = fourth_edge_opp ^ 1;
                                int fst_diag = GetEdgeIndex(u, third_vertex);
                                int snd_diag = GetEdgeIndex(v, fourth_vertex);
                                local_four_cycles[i].emplace_back(FourMotif(
                                    {i, snd_edge, third_edge, fourth_edge},
                                    {fst_diag, snd_diag}));
                                num_four_cycles++;
                            }
                        }
                    }
                }
            }
            done += GetDegree(u) * GetDegree(v);
        }
        timer.Stop();
        std::cout << "[Perf] EnumerateLocalFourCycles completed. "
                  << "Cycles: " << num_four_cycles << ", "
                  << "Time: " << timer.GetTime() << "ms"
                  << std::endl;
    }
#endif

#ifdef INDEX_PAR_v1
    void FourCycleProcessEdgeTask(GraphLib::Graph *G, int edge_index_lower, int edge_index_upper, std::atomic_long *num_four_cycles, std::atomic_long *global_done)
    {
        long local_num_four_cycles = 0;
        long local_done = 0;
        auto &edge_list = G->edge_list;
        for (int edge_index = edge_index_lower; edge_index < edge_index_upper; edge_index++)
        {
            auto &local_four_cycle_list = G->local_four_cycles[edge_index];
            auto &[u, v] = edge_list[edge_index];
            if (G->GetDegree(u) < G->GetDegree(v))
            {
                for (int &fourth_edge_opp : G->GetAllIncidentEdges(u))
                {
                    int fourth_vertex = G->GetOppositePoint(fourth_edge_opp);
                    if (fourth_vertex == v)
                        continue;
                    if (G->GetDegree(fourth_vertex) < G->GetDegree(v))
                    {
                        for (int &third_edge_opp : G->GetAllIncidentEdges(fourth_vertex))
                        {
                            int third_vertex = G->GetOppositePoint(third_edge_opp);
                            if (third_vertex == u)
                                continue;
                            int snd_edge = G->GetEdgeIndex(v, third_vertex);
                            if (snd_edge != -1)
                            {
                                int fourth_edge = fourth_edge_opp ^ 1;
                                int third_edge = third_edge_opp ^ 1;
                                int fst_diag = G->GetEdgeIndex(u, third_vertex);
                                int snd_diag = G->GetEdgeIndex(v, fourth_vertex);
                                local_four_cycle_list.push_back(Graph::FourMotif(
                                    {edge_index, snd_edge, third_edge, fourth_edge},
                                    {fst_diag, snd_diag}));
                                local_num_four_cycles++;
                            }
                        }
                    }
                    else
                    {
                        for (int &snd_edge : G->GetAllIncidentEdges(v))
                        {
                            int third_vertex = G->GetOppositePoint(snd_edge);
                            if (third_vertex == u)
                                continue;
                            int third_edge = G->GetEdgeIndex(third_vertex, fourth_vertex);
                            if (third_edge != -1)
                            {
                                int fourth_edge = fourth_edge_opp ^ 1;
                                int fst_diag = G->GetEdgeIndex(u, third_vertex);
                                int snd_diag = G->GetEdgeIndex(v, fourth_vertex);
                                local_four_cycle_list.push_back(Graph::FourMotif(
                                    {edge_index, snd_edge, third_edge, fourth_edge},
                                    {fst_diag, snd_diag}));
                                local_num_four_cycles++;
                            }
                        }
                    }
                }
            }
            else
            {
                for (int &snd_edge : G->GetAllIncidentEdges(v))
                {
                    int third_vertex = G->GetOppositePoint(snd_edge);
                    if (third_vertex == u)
                        continue;
                    if (G->GetDegree(third_vertex) < G->GetDegree(u))
                    {
                        for (int &third_edge : G->GetAllIncidentEdges(third_vertex))
                        {
                            int fourth_vertex = G->GetOppositePoint(third_edge);
                            if (fourth_vertex == v)
                                continue;
                            int fourth_edge = G->GetEdgeIndex(fourth_vertex, u);
                            if (fourth_edge != -1)
                            {
                                int fst_diag = G->GetEdgeIndex(u, third_vertex);
                                int snd_diag = G->GetEdgeIndex(v, fourth_vertex);
                                local_four_cycle_list.push_back(Graph::FourMotif(
                                    {edge_index, snd_edge, third_edge, fourth_edge},
                                    {fst_diag, snd_diag}));
                                local_num_four_cycles++;
                            }
                        }
                    }
                    else
                    {
                        for (int &fourth_edge_opp : G->GetAllIncidentEdges(u))
                        {
                            int fourth_vertex = G->GetOppositePoint(fourth_edge_opp);
                            if (fourth_vertex == v)
                                continue;
                            int third_edge = G->GetEdgeIndex(third_vertex, fourth_vertex);
                            if (third_edge != -1)
                            {
                                int fourth_edge = fourth_edge_opp ^ 1;
                                int fst_diag = G->GetEdgeIndex(u, third_vertex);
                                int snd_diag = G->GetEdgeIndex(v, fourth_vertex);
                                local_four_cycle_list.push_back(Graph::FourMotif(
                                    {edge_index, snd_edge, third_edge, fourth_edge},
                                    {fst_diag, snd_diag}));
                                local_num_four_cycles++;
                            }
                        }
                    }
                }
            }
            local_done += G->GetDegree(u) * G->GetDegree(v);
        }
        num_four_cycles->fetch_add(local_num_four_cycles);
        global_done->fetch_add(local_done);
    }
    void Graph::data_EnumerateLocalFourCycles()
    {
        Timer timer;
        timer.Start();

        local_four_cycles.resize(GetNumEdges());
        double total_required = 0;
        for (int i = 0; i < GetNumEdges(); i++)
        {
            auto &[u, v] = edge_list[i];
            total_required += GetDegree(u) * GetDegree(v);
        }
        std::atomic_long num_four_cycles_atomic(0);
        std::atomic_long done(0);
        omp_set_num_threads(GraphLib::num_threads);
        std::cout << "Set the number of threads to " << GraphLib::num_threads << std::endl;
        std::cout << "[Perf] Data_EnumerateLocalFourCycles started. " << omp_get_max_threads() << " threads." << std::endl;

#pragma omp parallel num_threads(GraphLib::num_threads) proc_bind(close)
        {
#pragma omp single
            {
                long current_workload = 0;
                long group_workload = total_required / (omp_get_max_threads() * 4);
                int current_index_start = 0;

                for (int i = 0; i < GetNumEdges(); i++)
                {
                    auto &[u, v] = edge_list[i];
                    current_workload += (long)GetDegree(u) * GetDegree(v);
                    if (current_workload > group_workload)
                    {
// 触发一个新任务
#pragma omp task
                        {
                            FourCycleProcessEdgeTask(this, current_index_start, i + 1, &num_four_cycles_atomic, &done);
                        }
                        current_index_start = i + 1;
                        current_workload = 0;
                    }
                    else if (i == GetNumEdges() - 1)
                    {
// 处理最后一组任务
#pragma omp task
                        {
                            FourCycleProcessEdgeTask(this, current_index_start, i + 1, &num_four_cycles_atomic, &done);
                        }
                        current_index_start = i + 1;
                        current_workload = 0;
                    }
                }
            }
        }
#pragma omp taskwait
        timer.Stop();
        std::cout << "[Perf] EnumerateLocalFourCycles completed. "
                  << "Cycles: " << num_four_cycles_atomic.load() << ", "
                  << "Time: " << timer.GetTime() << "ms"
                  << std::endl;
    }
#endif

#ifdef PULLVERSION
    /** 线程队列主动拉取版本 */
    void Graph::data_EnumerateLocalFourCycles()
    {
        Timer timer;
        timer.Start();
        local_four_cycles.resize(GetNumEdges());
        // 使用线程池主动拉取的版本
        double total_required = 0;
        for (int i = 0; i < GetNumEdges(); i++)
        {
            auto &[u, v] = edge_list[i];
            total_required += GetDegree(u) * GetDegree(v);
        }
        std::atomic_long num_four_cycles_atomic(0);
        std::atomic_long done(0);
        omp_set_num_threads(GraphLib::num_threads);
        std::cout << "Set the number of threads to " << GraphLib::num_threads << std::endl;
        std::cout << "[Perf] Data_EnumerateLocalFourCycles started. " << omp_get_max_threads() << " threads." << std::endl;
        // 计算任务队列
        tbb::concurrent_queue<std::pair<int, int>> task_queue;
        long current_workload = 0;
        long group_workload = total_required / (omp_get_max_threads() * 4);
        int current_index_start = 0;
        for (int i = 0; i < GetNumEdges(); i++)
        {
            auto &[u, v] = edge_list[i];
            current_workload += (long)GetDegree(u) * GetDegree(v);
            if (current_workload > group_workload)
            {
                task_queue.push({current_index_start, i + 1});
                current_index_start = i + 1;
                current_workload = 0;
            }
            else if (i == GetNumEdges() - 1)
            {
                task_queue.push({current_index_start, i + 1});
                current_index_start = i + 1;
                current_workload = 0;
            }
        }
// 启动线程
#pragma omp parallel
        {
            while (!task_queue.empty())
            {
                std::pair<int, int> t;
                auto flag = task_queue.try_pop(t);
                auto [edge_index_lb, edge_index_up] = t;
                if (!flag)
                    break;
                FourCycleProcessEdgeTask(this, edge_index_lb, edge_index_up, &num_four_cycles_atomic, &done);
            }
        }
        timer.Stop();
        std::cout << "[Perf] EnumerateLocalFourCycles completed. "
                  << "Cycles: " << num_four_cycles_atomic.load() << ", "
                  << "Time: " << timer.GetTime() << "ms"
                  << std::endl;
    }
#endif

#ifdef INDEX_PAR_v2

    void ForthEdgeCase(Graph *G, int i, int u, int v, int ff_low, int ff_up, std::atomic_long *global_num_four_cycles)
    {
        std::vector<Graph::FourMotif> local_four_cycles;
        long num_four_cycles = 0;
        for(int ff = ff_low; ff < ff_up; ff++)
        {
            auto &fourth_edge_opp = G->GetAllIncidentEdges(u)[ff];
            int fourth_vertex = G->GetOppositePoint(fourth_edge_opp);
            if (fourth_vertex == v)
                continue;
            if (G->GetDegree(fourth_vertex) < G->GetDegree(v))
            {
                for (int &third_edge_opp : G->GetAllIncidentEdges(fourth_vertex))
                {
                    int third_vertex = G->GetOppositePoint(third_edge_opp);
                    if (third_vertex == u)
                        continue;
                    int snd_edge = G->GetEdgeIndex(v, third_vertex);
                    if (snd_edge != -1)
                    {
                        int fourth_edge = fourth_edge_opp ^ 1;
                        int third_edge = third_edge_opp ^ 1;
                        int fst_diag = G->GetEdgeIndex(u, third_vertex);
                        int snd_diag = G->GetEdgeIndex(v, fourth_vertex);
                        local_four_cycles.emplace_back(Graph::FourMotif(
                            {i, snd_edge, third_edge, fourth_edge},
                            {fst_diag, snd_diag}));
                        num_four_cycles++;
                    }
                }
            }
            else
            {
                for (int &snd_edge : G->GetAllIncidentEdges(v))
                {
                    int third_vertex = G->GetOppositePoint(snd_edge);
                    if (third_vertex == u)
                        continue;
                    int third_edge = G->GetEdgeIndex(third_vertex, fourth_vertex);
                    if (third_edge != -1)
                    {
                        int fourth_edge = fourth_edge_opp ^ 1;
                        int fst_diag = G->GetEdgeIndex(u, third_vertex);
                        int snd_diag = G->GetEdgeIndex(v, fourth_vertex);
                        local_four_cycles.emplace_back(Graph::FourMotif(
                            {i, snd_edge, third_edge, fourth_edge},
                            {fst_diag, snd_diag}));
                        num_four_cycles++;
                    }
                }
            }
        }
        G->local_four_cycles_tmp[i].grow_by(local_four_cycles.begin(), local_four_cycles.end());
        global_num_four_cycles->fetch_add(num_four_cycles);
    }

    void SecondEdgeCase(Graph *G, int i, int u, int v, int ss_low, int ss_up, std::atomic_long *global_num_four_cycles)
    {
        std::vector<Graph::FourMotif> local_four_cycles;
        long num_four_cycles = 0;
        for(int ss = ss_low; ss < ss_up; ss++)
        {
            int &snd_edge = G->GetAllIncidentEdges(v)[ss];
            int third_vertex = G->GetOppositePoint(snd_edge);
            if (third_vertex == u)
                continue;
            if (G->GetDegree(third_vertex) < G->GetDegree(u))
            {
                for (int &third_edge : G->GetAllIncidentEdges(third_vertex))
                {
                    int fourth_vertex = G->GetOppositePoint(third_edge);
                    if (fourth_vertex == v)
                        continue;
                    int fourth_edge = G->GetEdgeIndex(fourth_vertex, u);
                    if (fourth_edge != -1)
                    {
                        int fst_diag = G->GetEdgeIndex(u, third_vertex);
                        int snd_diag = G->GetEdgeIndex(v, fourth_vertex);
                        local_four_cycles.emplace_back(Graph::FourMotif(
                            {i, snd_edge, third_edge, fourth_edge},
                            {fst_diag, snd_diag}));
                        num_four_cycles++;
                    }
                }
            }
            else
            {
                for (int &fourth_edge_opp : G->GetAllIncidentEdges(u))
                {
                    int fourth_vertex = G->GetOppositePoint(fourth_edge_opp);
                    if (fourth_vertex == v)
                        continue;
                    int third_edge = G->GetEdgeIndex(third_vertex, fourth_vertex);
                    if (third_edge != -1)
                    {
                        int fourth_edge = fourth_edge_opp ^ 1;
                        int fst_diag = G->GetEdgeIndex(u, third_vertex);
                        int snd_diag = G->GetEdgeIndex(v, fourth_vertex);
                        local_four_cycles.emplace_back(Graph::FourMotif(
                            {i, snd_edge, third_edge, fourth_edge},
                            {fst_diag, snd_diag}));
                        num_four_cycles++;
                    }
                }
            }
        }
        G->local_four_cycles_tmp[i].grow_by(local_four_cycles.begin(), local_four_cycles.end());
        global_num_four_cycles->fetch_add(num_four_cycles);
    }


    long EntryDataEnumerateLocalFourCycles(Graph *G)
    {
        long total_required = 0;
        for (int i = 0; i < G->GetNumEdges(); i++)
        {
            auto &[u, v] = G->edge_list[i];
            total_required += G->GetDegree(u) * G->GetDegree(v);
        }
        double avg_workload = total_required / (double)G->GetNumEdges();
        std::atomic_long num_four_cycles = 0;
        auto num_four_cycles_ptr = &num_four_cycles;
        auto num_edges = G->GetNumEdges();
#pragma omp parallel num_threads(GraphLib::num_threads) proc_bind(close)
        {
#pragma omp single
            {
#pragma omp taskloop num_tasks(GraphLib::num_threads * 4) shared(G)
                for (int i = 0; i < num_edges; i++)
                {
                    auto [u, v] = G->edge_list[i];
                    if (G->GetDegree(u) < G->GetDegree(v))
                    {
                        int sz = G->GetAllIncidentEdges(u).size();
                        if (sz > avg_workload)
                        {
                            int chunk_size = sz / (GraphLib::num_threads) + 1;
                            int start = 0;
                            for(start = 0; start < sz; start += chunk_size) {
                                int end = std::min(start + chunk_size, sz);
                                #pragma omp task shared(G, num_four_cycles_ptr) firstprivate(i, u, v, start, end)
                                ForthEdgeCase(G, i, u, v, start, end, num_four_cycles_ptr);
                            }
                        }
                        else
                        {
                            ForthEdgeCase(G, i, u, v, 0, sz, num_four_cycles_ptr);
                        }
                    }
                    else
                    {
                        int sz= G->GetAllIncidentEdges(v).size();
                        if (sz > avg_workload)
                        {
                            int chunk_size = sz / (GraphLib::num_threads) + 1;
                            int start = 0;
                            for(start = 0; start < sz; start += chunk_size) {
                                int end = std::min(start + chunk_size, sz);
                                #pragma omp task shared(G, num_four_cycles_ptr) firstprivate(i, u, v, start, end)
                                SecondEdgeCase(G, i, u, v, start, end, num_four_cycles_ptr);
                            }
                        }
                        else
                        {
                            SecondEdgeCase(G, i , u, v, 0, sz, num_four_cycles_ptr);
                        }
                        
                    }
                }
            #pragma omp taskwait
            }
        }
        return num_four_cycles.load();
    }

    void Graph::data_EnumerateLocalFourCycles()
    {
        Timer timer;
        timer.Start();

        local_four_cycles.resize(GetNumEdges());
        local_four_cycles_tmp.resize(GetNumEdges());
     
        long num_four_cycles = -1;
        num_four_cycles = EntryDataEnumerateLocalFourCycles(this);
        std::cerr << "Copy back to serial four cycle structures..." << std::endl;
        // 拷贝回串行结构
        #pragma omp parallel for num_threads(GraphLib::num_threads) proc_bind(close)
        for(int i = 0; i < GetNumEdges(); i++)
        {
            local_four_cycles[i].reserve(local_four_cycles_tmp[i].size());
            local_four_cycles[i].insert(local_four_cycles[i].end(), local_four_cycles_tmp[i].begin(), local_four_cycles_tmp[i].end());
        }
        local_four_cycles_tmp.clear();

        timer.Stop();
        std::cout << "[Perf] EnumerateLocalFourCycles completed. "
                  << "Cycles: " << num_four_cycles << ", "
                  << "Time: " << timer.GetTime() << "ms"
                  << std::endl;
    }
#endif

    void Graph::ChibaNishizeki()
    {
        std::vector<int> vertices_by_degree(GetNumVertices(), 0);
        for (int i = 0; i < GetNumVertices(); i++)
            vertices_by_degree[i] = i;
        std::sort(vertices_by_degree.begin(), vertices_by_degree.end(), [this](int a, int b) -> bool
                  { return GetDegree(a) > GetDegree(b); });
    }
}