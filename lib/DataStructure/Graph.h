#pragma once
#include "Base/Base.h"
#include <oneapi/tbb/concurrent_vector.h>
#include <unordered_map>
#include <iostream>
#include <atomic>
#include <omp.h>
#include <tbb/concurrent_vector.h>
#include "Base/Timer.h"

#include "config.h"
namespace GraphLib {
    int num_threads = 4;          // 默认值
    int group_size = 64;          // 默认值
    int incident_edges_size = 50000; // 默认值
}

#define INDEX_PAR_v2

// #define HUGE_GRAPH
namespace GraphLib {
    class Graph {
    public:
        // Adjacency List
        std::vector<std::vector<int>> adj_list;
        std::vector<int> core_num, vertex_color;
        std::vector<int> degeneracy_order;
        int num_vertex = 0, num_edge = 0, max_degree = 0, degeneracy = 0, num_color = 0;
        int num_vertex_labels = 0;

        /**
         * Basic data structures for graph
         * @attribute (vertex/edge)_label : array of labels
         * @attribute edge_list : list of edges as pair<int, int> form
         * @attribute incident_edges[v][l] : list of indices of incident edges from v and endpoint label l
         * @attribute all_incident_edges[v] : list of indices of all incident edges from v
         * @attribute edge_index_map : Queryable as map[{u, v}].
         */
        std::vector<int> vertex_label, edge_label, edge_to;
        std::vector<std::pair<int, int>> edge_list;
        std::vector<std::vector<int>> all_incident_edges;
#ifdef HUGE_GRAPH
        std::vector<std::map<int, std::vector<int>>> incident_edges;
#else
        std::vector<std::vector<std::vector<int>>> incident_edges;
#endif
        std::vector<std::unordered_map<int, int>> edge_index_map;


        /*
         * Enumeration of Small Cycles for Cyclic Substructure Filter
         * For each edge e, store local triangles and four-cycles
         */
        struct FourMotif {
            std::tuple<int, int, int, int> edges;
            std::tuple<int, int> diags;
            FourMotif(std::tuple<int, int, int, int> edges, std::tuple<int, int> diags) : edges(edges), diags(diags) {}
        };
        std::vector<std::vector<std::tuple<int, int, int>>> local_triangles;
        #ifdef INDEX_PAR_v1
        std::vector<std::vector<FourMotif>> local_four_cycles;
        #endif
        #ifdef INDEX_PAR_v2
        std::vector<std::vector<FourMotif>> local_four_cycles;
        std::vector<tbb::concurrent_vector<FourMotif>> local_four_cycles_tmp;
        #endif

        // NUMA-aware内存初始化
        void NUMA_InitLocalFourCycles(int num_edges) {
            local_four_cycles.resize(num_edges);
            #pragma omp parallel for
            for (int i = 0; i < num_edges; ++i) {
                // first-touch
                local_four_cycles[i].reserve(100);
            }
        }

        // 辅助内联函数：检查边是否存在并返回对边
        inline int GetValidOppositeEdge(int u, int fourth_vertex) {
            int edge_opp = GetEdgeIndex(u, fourth_vertex);
            return (edge_opp == -1) ? -1 : (edge_opp ^ 1);
        }

        // 封装生成 FourMotif 的通用函数
        inline void AddFourMotif(int edge_idx, int snd_edge, int third_edge, int fourth_edge,
                int fst_diag, int snd_diag, std::vector<FourMotif>& results) {
                results.emplace_back(FourMotif{{edge_idx, snd_edge, third_edge, fourth_edge},
                       {fst_diag, snd_diag}});
        }
        
        // 优化后的 ProcessAdjacencyBranch
        void ProcessAdjacencyBranch(int edge_idx, int u, int v, int fourth_vertex, bool use_alt_branch,
            std::vector<FourMotif>& local_results) {
            // 缓存目标顶点 incident 边集合，避免重复查询
            const auto incidentEdges = GetAllIncidentEdges(use_alt_branch ? v : fourth_vertex);
            if (use_alt_branch) {
                // 分支：以 v 的 incident 边为主
                for (int &snd_edge : GetAllIncidentEdges(v)) {
                    const int third_vertex = GetOppositePoint(snd_edge);
                    if (third_vertex == u) continue;
                    int third_edge = GetEdgeIndex(third_vertex, fourth_vertex);
                    if (third_edge != -1) {
                        int fourth_edge = GetValidOppositeEdge(u, fourth_vertex);
                        if (fourth_edge == -1) continue;
                            int fst_diag = GetEdgeIndex(u, third_vertex);
                            int snd_diag = GetEdgeIndex(v, fourth_vertex);
                            AddFourMotif(edge_idx, snd_edge, third_edge, fourth_edge, fst_diag, snd_diag, local_results);
                    }
                }
            } else {
                // 分支：以 fourth_vertex 的 incident 边为主（遍历第三顶点来自 fourth_vertex 的 incident 边）
                for (int &third_edge_opp : GetAllIncidentEdges(fourth_vertex)) {
                    const int third_vertex = GetOppositePoint(third_edge_opp);
                    if (third_vertex == u) continue;
                    int snd_edge = GetEdgeIndex(v, third_vertex);
                    if (snd_edge != -1) {
                        int fourth_edge = GetValidOppositeEdge(u, fourth_vertex);
                        if (fourth_edge == -1) continue;
                            // 注意：此处 third_edge 为反向边
                            int third_edge = third_edge_opp ^ 1;
                            int fst_diag = GetEdgeIndex(u, third_vertex);
                            int snd_diag = GetEdgeIndex(v, fourth_vertex);
                            AddFourMotif(edge_idx, snd_edge, third_edge, fourth_edge, fst_diag, snd_diag, local_results);
                    }
                }
            }
        }

        // 优化后的 ProcessAdjacencyBranch_Sym
        void ProcessAdjacencyBranch_Sym(int edge_idx, int u, int v, int third_vertex, int snd_edge, 
            bool use_alt, std::vector<FourMotif>& local_results) {
            if (!use_alt) {
                // 分支1：遍历第三顶点的 incident 边寻找第四顶点
                auto thirdEdges = GetAllIncidentEdges(third_vertex); // 缓存边集合
                for (int &third_edge : thirdEdges) {
                    int fourth_vertex = GetOppositePoint(third_edge);
                    if (fourth_vertex == v) continue;
                    int fourth_edge = GetValidOppositeEdge(u, fourth_vertex);
                    if (fourth_edge == -1) continue;
                    int fst_diag = GetEdgeIndex(u, third_vertex);
                    int snd_diag = GetEdgeIndex(v, fourth_vertex);
                    AddFourMotif(edge_idx, snd_edge, third_edge, fourth_edge, fst_diag, snd_diag, local_results);
                }
            }else {
                // 分支2：遍历 u 的 incident 边以候选第四顶点构成四元环
                auto uEdges = GetAllIncidentEdges(u);
                for (int &fourth_edge_opp : uEdges) {
                    int fourth_vertex = GetOppositePoint(fourth_edge_opp);
                    if (fourth_vertex == v) continue;
                    int third_edge = GetEdgeIndex(third_vertex, fourth_vertex);
                    if (third_edge != -1) {
                        int fourth_edge = fourth_edge_opp ^ 1;
                        int fst_diag = GetEdgeIndex(u, third_vertex);
                        int snd_diag = GetEdgeIndex(v, fourth_vertex);
                        AddFourMotif(edge_idx, snd_edge, third_edge, fourth_edge, fst_diag, snd_diag, local_results);
                    }
                }
            }
        }

    public:
        Graph() {}
        ~Graph() {}
        Graph &operator=(const Graph &) = delete;

        std::vector<int>& GetNeighbors(int v) {
            return adj_list[v];
        }
        

        inline int GetDegree(int v) const {
            return adj_list[v].size();
        }

        inline int GetNumVertices() const {
            return num_vertex;
        }

        inline int GetNumEdges() const {
            return num_edge;
        }

        inline int GetMaxDegree() const {
            return max_degree;
        }

        void ComputeCoreNum();

        inline int GetCoreNum(int v) const {
            return core_num[v];
        }

        inline int GetDegeneracy() const {return degeneracy;}

        void AssignVertexColor();

        inline int GetNumColors() const {return num_color;}

        inline int GetVertexColor(int v) const {return vertex_color[v];}


        void LoadLabeledGraph(const std::string &filename);

        inline std::vector<int>& GetAllIncidentEdges(int v) {return all_incident_edges[v];}
        inline std::vector<int>& GetIncidentEdges(int v, int label) {return incident_edges[v][label];}
        inline int GetVertexLabel(int v) const {return vertex_label[v];}
        inline int GetEdgeLabel(int edge_id) const {return edge_label[edge_id];}
        inline int GetNumLabels() const {return num_vertex_labels;}
        inline int GetOppositeEdge(int edge_id) const {return edge_id^1;}
        inline int GetOppositePoint(int edge_id) const {return edge_to[edge_id];}
        inline int GetEdgeIndex(int u, int v) {
            auto it = edge_index_map[u].find(v);
            return (it == edge_index_map[u].end() ? -1 : it->second);
        }
        inline std::pair<int, int>& GetEdge(int edge_id) {
            return edge_list[edge_id];
        }

        inline std::vector<std::tuple<int, int, int>>& GetLocalTriangles(int edge_id) {return local_triangles[edge_id];}

        #if defined(INDEX_PAR_v1)
        inline std::vector<FourMotif>& GetLocalFourCycles(int edge_id) {return local_four_cycles[edge_id];}
        #elif defined(INDEX_PAR_v2)
        inline std::vector<FourMotif>& GetLocalFourCycles(int edge_id) {return local_four_cycles[edge_id];}
        #endif

        void EnumerateLocalTriangles();
        void data_EnumerateLocalFourCycles();
        void query_EnumerateLocalFourCycles();
        void ChibaNishizeki();

        /**
         * @brief Build the incidence list structure
         */
        void BuildIncidenceList();

        void LoadGraph(std::vector<int> &vertex_labels, std::vector<std::pair<int, int>> &edges,
                       std::vector<int> &edge_labels,   bool directed = false);

        void WriteToFile(string filename);
    };

    /**
     * @brief Compute the core number of each vertex
     * @date Oct 21, 2022
     */
    void Graph::ComputeCoreNum() {
        Timer ComputeCoreNumtimer;
        ComputeCoreNumtimer.Start();

        core_num.resize(num_vertex, 0);
        int *bin = new int[GetMaxDegree() + 1];
        int *pos = new int[GetNumVertices()];
        int *vert = new int[GetNumVertices()];

        std::fill(bin, bin + (GetMaxDegree() + 1), 0);

        for (int v = 0; v < GetNumVertices(); v++) {
            core_num[v] = adj_list[v].size();
            bin[core_num[v]] += 1;
        }

        int start = 0;
        int num;

        for (int d = 0; d <= GetMaxDegree(); d++) {
            num = bin[d];
            bin[d] = start;
            start += num;
        }

        for (int v = 0; v < GetNumVertices(); v++) {
            pos[v] = bin[core_num[v]];
            vert[pos[v]] = v;
            bin[core_num[v]] += 1;
        }

        for (int d = GetMaxDegree(); d--;)
            bin[d + 1] = bin[d];
        bin[0] = 0;

        for (int i = 0; i < GetNumVertices(); i++) {
            int v = vert[i];

            for (int u : GetNeighbors(v)) {
                if (core_num[u] > core_num[v]) {
                    int du = core_num[u];
                    int pu = pos[u];
                    int pw = bin[du];
                    int w = vert[pw];

                    if (u != w) {
                        pos[u] = pw;
                        pos[w] = pu;
                        vert[pu] = w;
                        vert[pw] = u;
                    }

                    bin[du]++;
                    core_num[u]--;
                }
            }
        }
        degeneracy_order.resize(GetNumVertices());
        for (int i = 0; i < GetNumVertices(); i++) {
            degeneracy_order[i] = vert[i];
        }
        std::reverse(degeneracy_order.begin(),degeneracy_order.end());

        degeneracy = 0;
        for (int i = 0; i < GetNumVertices(); i++) {
            degeneracy = std::max(core_num[i], degeneracy);
        }

        delete[] bin;
        delete[] pos;
        delete[] vert;
        ComputeCoreNumtimer.Stop();
        std::cout << "[Perf] ComputeCoreNumTime: " << ComputeCoreNumtimer.GetTime() << "ms" << std::endl;
    }

    /**
     * @brief Greedy coloring of the graph, following the given initial order of vertices.
     * @date Sep 16, 2022
     */
    void Graph::AssignVertexColor() {
        vertex_color.resize(GetNumVertices(), -1);
        num_color = 0;
        bool *used = new bool[GetNumVertices()];
        for (int vertexID : degeneracy_order) {
            for (int neighbor : adj_list[vertexID]) {
                if (vertex_color[neighbor] == -1) continue;
                used[vertex_color[neighbor]] = true;
            }
            int c = 0; while (used[c]) c++;
            vertex_color[vertexID] = c;
            num_color = std::max(num_color, c+1);
            for (int neighbor : adj_list[vertexID]) {
                if (vertex_color[neighbor] == -1) continue;
                used[vertex_color[neighbor]] = false;
            }
        }
    }



    void Graph::LoadLabeledGraph(const std::string &filename) {
        Timer LoadLabeledGraphtimer;
        LoadLabeledGraphtimer.Start();

        std::ifstream fin(filename);
        int v, e;
        std::string ignore, type, line;
        fin >> ignore >> v >> e;
        num_vertex = v;
        // add edges in both directions
        num_edge = e * 2;
        adj_list.resize(num_vertex);
        vertex_label.resize(num_vertex);
        edge_label.resize(num_edge);
        int num_lines = 0;
        while (getline(fin, line)) {
            auto tok = parse(line, " ");
            type = tok[0];
            tok.pop_front();
            if (type[0] == 'v') {
                int id = std::stoi(tok.front());
                tok.pop_front();
                int l;
                if (tok.empty()) l = 0;
                else {
                    l = std::stoi(tok.front());
                    tok.pop_front();
                }
                vertex_label[id] = l;
            }
            else if (type[0] == 'e') {
                int v1, v2;
                v1 = std::stoi(tok.front()); tok.pop_front();
                v2 = std::stoi(tok.front()); tok.pop_front();
                adj_list[v1].push_back(v2);
                adj_list[v2].push_back(v1);
                edge_to.push_back(v2); edge_to.push_back(v1);
                edge_list.push_back({v1, v2});
                edge_list.push_back({v2, v1});
                int el = tok.empty() ? 0 : std::stoi(tok.front());
                edge_label[edge_list.size()-2] = edge_label[edge_list.size()-1] = el;
                max_degree = std::max(max_degree, (int)std::max(adj_list[v1].size(), adj_list[v2].size()));
            }
            num_lines++;
        }
        LoadLabeledGraphtimer.Stop();
        std::cout << "[Perf] LoadLabeledGraphTime: " << LoadLabeledGraphtimer.GetTime() << "ms" << std::endl;
    }

    void Graph::LoadGraph(std::vector<int> &vertex_labels,
                          std::vector<std::pair<int, int>> &edges,
                          std::vector<int> &edge_labels,
                          bool directed) {
        num_vertex = vertex_labels.size();
        num_edge = edges.size();
        if (!directed) num_edge *= 2;
        adj_list.resize(num_vertex);
        vertex_label.resize(num_vertex);
        edge_label.resize(num_edge);
        for (int i = 0; i < num_vertex; i++) vertex_label[i] = vertex_labels[i];
        for (int i = 0; i < edges.size(); i++) {
            auto &[v1, v2] = edges[i];
            int el = (edge_labels.size() > i) ? edge_labels[i] : 0;
            adj_list[v1].push_back(v2);
            edge_to.push_back(v2);
            edge_list.push_back({v1, v2});
            edge_label[edge_list.size()-1] = el;
//            fprintf(stderr, "Edge %d %d\n", v1, v2);
            if (!directed) {
                adj_list[v2].push_back(v1);
                edge_to.push_back(v1);
                edge_list.push_back({v2, v1});
                edge_label[edge_list.size()-2] = edge_label[edge_list.size()-1] = el;
            }
        }
    }


    void Graph::BuildIncidenceList() {
        Timer BuildIncidenceListtimer;
        BuildIncidenceListtimer.Start();

        all_incident_edges.resize(num_vertex);
        incident_edges.resize(num_vertex);
        edge_index_map.resize(num_vertex);
        for (int i = 0; i < GetNumVertices(); i++) {
#ifndef HUGE_GRAPH
            incident_edges[i].resize(GetNumLabels());
#endif
        }
        int edge_id = 0;
        for (auto& [u, v] : edge_list) {
            all_incident_edges[u].push_back(edge_id);
            incident_edges[u][GetVertexLabel(v)].push_back(edge_id);
            edge_index_map[u][v] = edge_id;
            edge_id++;
        }

        // sort edges by degree of endpoint
        for (int i = 0; i < GetNumVertices(); i++) {
#ifdef HUGE_GRAPH
            for (auto &[l, vec] : incident_edges[i]) {
                std::stable_sort(vec.begin(), vec.end(),[this](auto &a, auto &b) -> bool {
                    int opp_a = edge_list[a].second;
                    int opp_b = edge_list[b].second;
                    return adj_list[opp_a].size() > adj_list[opp_b].size();
                });
            }
#else
            for (auto &vec : incident_edges[i]) {
                std::stable_sort(vec.begin(), vec.end(),[this](auto &a, auto &b) -> bool {
                    int opp_a = edge_list[a].second;
                    int opp_b = edge_list[b].second;
                    return adj_list[opp_a].size() > adj_list[opp_b].size();
                });
            }
#endif
            std::stable_sort(all_incident_edges[i].begin(), all_incident_edges[i].end(), [this](auto &a, auto &b) -> bool {
                return adj_list[edge_list[a].second].size() > adj_list[edge_list[b].second].size();
            });
        }
        BuildIncidenceListtimer.Stop();
        std::cout << "[Perf] BuildIncidenceListTime: " << BuildIncidenceListtimer.GetTime() << "ms" << std::endl;
    }

    void Graph::WriteToFile(std::string filename) {
        std::filesystem::path filepath = filename;
        std::filesystem::create_directories(filepath.parent_path());
        std::ofstream out(filename);
        out << "t " << GetNumVertices() << ' ' << GetNumEdges()/2 << '\n';
        for (int i = 0; i < GetNumVertices(); i++) {
            out << "v " << i << ' ' << GetVertexLabel(i) << ' ' << GetDegree(i) << '\n';
        }
        int idx = 0;
        for (auto &e : edge_list) {
            if (e.first < e.second) {
                out << "e " << e.first << ' ' << e.second << ' ' << GetEdgeLabel(idx) << '\n';
            }
            idx++;
        }
    }
}
