#pragma once
/**
* @brief Class for data graph in pattern matching related problems
* @type Assume undirected, connected, labeled graph
*/
#include <algorithm>
#include <fstream>
#include <unordered_map>
#include <filesystem>
#include "DataStructure/Graph.h"
#include "Base/Timer.h"

namespace GraphLib { namespace SubgraphMatching {
    struct LabelStatistics {
        std::vector<double> vertex_label_probability, edge_label_probability;
        double vertex_label_entropy = 0.0, edge_label_entropy = 0.0;
    };
    class DataGraph : public GraphLib::Graph {
    protected:
        // array of vertices, grouped by label, ordered by decreasing order of degree
        std::vector<std::vector<int>> vertex_by_labels;
        // num_vertex_by_label_degree;
        std::unordered_map<int, int> transferred_label_map;
        LabelStatistics label_statistics;
    public:
        DataGraph(const Graph &g) : Graph(g) {};
        DataGraph(){};
        std::vector<int>& GetVerticesByLabel(int label) { return vertex_by_labels[label]; }
        inline int GetTransferredLabel(int l) {return transferred_label_map[l];}
        void Preprocess();
        void TransformLabel();
        void ComputeLabelStatistics();
        bool FourCycleEnumerated() {return !local_four_cycles.empty();}

        void SerializeIndex(const std::string& index_dir);
        void DeserializeIndex(const std::string& index_dir);
    };



    void DataGraph::TransformLabel() {
        Timer TransformLabeltimer;
        TransformLabeltimer.Start();

        int cur_transferred_label = 0;
        for (int v = 0; v < GetNumVertices(); v++) {
            int l = vertex_label[v];
            if (transferred_label_map.find(l) == transferred_label_map.end()) {
                transferred_label_map[l] = cur_transferred_label;
                cur_transferred_label += 1;
            }
            vertex_label[v] = transferred_label_map[l];
            num_vertex_labels = std::max(num_vertex_labels, vertex_label[v]+1);
        }
        TransformLabeltimer.Stop();
        std::cout << "[Perf] TransformLabelTime: " << TransformLabeltimer.GetTime() << "ms" << std::endl;
    }


    void DataGraph::ComputeLabelStatistics() {
        Timer ComputeLabelStatisticstimer;
        ComputeLabelStatisticstimer.Start();

        label_statistics.vertex_label_probability.resize(GetNumLabels(), 1e-4);
        for (int i = 0; i < GetNumVertices(); i++) {
            label_statistics.vertex_label_probability[GetVertexLabel(i)] += 1.0;
        }
        for (int i = 0; i < GetNumLabels(); i++) {
            label_statistics.vertex_label_probability[i] /= (1.0 * GetNumVertices());
        }
        for (auto x : label_statistics.vertex_label_probability) {
            label_statistics.vertex_label_entropy -= x * log2(x);
        }
        ComputeLabelStatisticstimer.Stop();
        std::cout << "[Perf] ComputeLabelStatisticsTime: " << ComputeLabelStatisticstimer.GetTime() << "ms" << std::endl;
    }


    void DataGraph::Preprocess() {
        for (auto &it : adj_list) max_degree = std::max(max_degree, (int)it.size());
        TransformLabel();
        BuildIncidenceList();
        ComputeCoreNum();
        ComputeLabelStatistics();

        Timer Preprocesstimer;
        Preprocesstimer.Start();
        vertex_by_labels.resize(GetNumLabels());
        // num_vertex_by_label_degree.resize(GetNumLabels());
        for (int i = 0; i < GetNumVertices(); i++) {
            vertex_by_labels[GetVertexLabel(i)].push_back(i);
        }
        for (int i = 0; i < GetNumLabels(); i++) {
            if (vertex_by_labels[i].empty()) continue;
            std::stable_sort(vertex_by_labels[i].begin(), vertex_by_labels[i].end(), [this](int a, int b) {
                return GetDegree(a) > GetDegree(b);
            });
        }
        Preprocesstimer.Stop();
        std::cout << "[Perf] Remain_PreprocessTime: " << Preprocesstimer.GetTime() << "ms" << std::endl;
    }

    // =========================================================================
    // Binary Serialization / Deserialization for offline index persistence
    // =========================================================================

    namespace detail {
        // Helper: write a POD value
        template<typename T>
        inline void bin_write(std::ofstream& out, const T& val) {
            out.write(reinterpret_cast<const char*>(&val), sizeof(T));
        }
        // Helper: read a POD value
        template<typename T>
        inline void bin_read(std::ifstream& in, T& val) {
            in.read(reinterpret_cast<char*>(&val), sizeof(T));
        }
        // Helper: write a vector of POD
        template<typename T>
        inline void bin_write_vec(std::ofstream& out, const std::vector<T>& vec) {
            size_t sz = vec.size();
            bin_write(out, sz);
            if (sz > 0) out.write(reinterpret_cast<const char*>(vec.data()), sz * sizeof(T));
        }
        // Helper: read a vector of POD
        template<typename T>
        inline void bin_read_vec(std::ifstream& in, std::vector<T>& vec) {
            size_t sz;
            bin_read(in, sz);
            vec.resize(sz);
            if (sz > 0) in.read(reinterpret_cast<char*>(vec.data()), sz * sizeof(T));
        }
        // Helper: write a vector of pairs
        inline void bin_write_pair_vec(std::ofstream& out, const std::vector<std::pair<int,int>>& vec) {
            size_t sz = vec.size();
            bin_write(out, sz);
            for (auto& [a,b] : vec) { bin_write(out, a); bin_write(out, b); }
        }
        inline void bin_read_pair_vec(std::ifstream& in, std::vector<std::pair<int,int>>& vec) {
            size_t sz;
            bin_read(in, sz);
            vec.resize(sz);
            for (auto& [a,b] : vec) { bin_read(in, a); bin_read(in, b); }
        }
    }

    void DataGraph::SerializeIndex(const std::string& index_dir) {
        namespace fs = std::filesystem;
        fs::create_directories(index_dir);

        Timer ser_timer; ser_timer.Start();

        // --- 1. Graph structure ---
        {
            std::ofstream out(index_dir + "/graph.bin", std::ios::binary);
            detail::bin_write(out, num_vertex);
            detail::bin_write(out, num_edge);
            detail::bin_write(out, max_degree);
            detail::bin_write(out, num_vertex_labels);
            detail::bin_write(out, degeneracy);

            // adj_list
            detail::bin_write(out, (size_t)adj_list.size());
            for (auto& v : adj_list) detail::bin_write_vec(out, v);

            detail::bin_write_vec(out, vertex_label);
            detail::bin_write_vec(out, edge_label);
            detail::bin_write_vec(out, edge_to);
            detail::bin_write_pair_vec(out, edge_list);
            detail::bin_write_vec(out, core_num);
            detail::bin_write_vec(out, degeneracy_order);

            // DataGraph-specific: vertex_by_labels
            detail::bin_write(out, (size_t)vertex_by_labels.size());
            for (auto& v : vertex_by_labels) detail::bin_write_vec(out, v);

            // transferred_label_map
            size_t map_sz = transferred_label_map.size();
            detail::bin_write(out, map_sz);
            for (auto& [k, v] : transferred_label_map) {
                detail::bin_write(out, k);
                detail::bin_write(out, v);
            }

            // label_statistics
            detail::bin_write_vec(out, label_statistics.vertex_label_probability);
            detail::bin_write_vec(out, label_statistics.edge_label_probability);
            detail::bin_write(out, label_statistics.vertex_label_entropy);
            detail::bin_write(out, label_statistics.edge_label_entropy);

            out.close();
        }

        // --- 2. Triangles ---
        {
            std::ofstream out(index_dir + "/triangles.bin", std::ios::binary);
            size_t n = local_triangles.size();
            detail::bin_write(out, n);
            for (size_t i = 0; i < n; i++) {
                size_t m = local_triangles[i].size();
                detail::bin_write(out, m);
                for (auto& [a,b,c] : local_triangles[i]) {
                    detail::bin_write(out, a);
                    detail::bin_write(out, b);
                    detail::bin_write(out, c);
                }
            }
            out.close();
        }

        // --- 3. Four-cycles ---
        {
            std::ofstream out(index_dir + "/four_cycles.bin", std::ios::binary);
            size_t n = local_four_cycles.size();
            detail::bin_write(out, n);
            for (size_t i = 0; i < n; i++) {
                size_t m = local_four_cycles[i].size();
                detail::bin_write(out, m);
                for (auto& fm : local_four_cycles[i]) {
                    auto& [e0,e1,e2,e3] = fm.edges;
                    auto& [d0,d1] = fm.diags;
                    detail::bin_write(out, e0);
                    detail::bin_write(out, e1);
                    detail::bin_write(out, e2);
                    detail::bin_write(out, e3);
                    detail::bin_write(out, d0);
                    detail::bin_write(out, d1);
                }
            }
            out.close();
        }

        ser_timer.Stop();
        std::cout << "[Perf] SerializeIndexTime: " << ser_timer.GetTime() << "ms" << std::endl;
    }

    void DataGraph::DeserializeIndex(const std::string& index_dir) {
        Timer deser_timer; deser_timer.Start();

        // --- 1. Graph structure ---
        {
            std::ifstream in(index_dir + "/graph.bin", std::ios::binary);
            if (!in) throw std::runtime_error("Cannot open " + index_dir + "/graph.bin");

            detail::bin_read(in, num_vertex);
            detail::bin_read(in, num_edge);
            detail::bin_read(in, max_degree);
            detail::bin_read(in, num_vertex_labels);
            detail::bin_read(in, degeneracy);

            // adj_list
            size_t adj_sz;
            detail::bin_read(in, adj_sz);
            adj_list.resize(adj_sz);
            for (auto& v : adj_list) detail::bin_read_vec(in, v);

            detail::bin_read_vec(in, vertex_label);
            detail::bin_read_vec(in, edge_label);
            detail::bin_read_vec(in, edge_to);
            detail::bin_read_pair_vec(in, edge_list);
            detail::bin_read_vec(in, core_num);
            detail::bin_read_vec(in, degeneracy_order);

            // DataGraph-specific: vertex_by_labels
            size_t vbl_sz;
            detail::bin_read(in, vbl_sz);
            vertex_by_labels.resize(vbl_sz);
            for (auto& v : vertex_by_labels) detail::bin_read_vec(in, v);

            // transferred_label_map
            size_t map_sz;
            detail::bin_read(in, map_sz);
            transferred_label_map.clear();
            for (size_t i = 0; i < map_sz; i++) {
                int k, v;
                detail::bin_read(in, k);
                detail::bin_read(in, v);
                transferred_label_map[k] = v;
            }

            // label_statistics
            detail::bin_read_vec(in, label_statistics.vertex_label_probability);
            detail::bin_read_vec(in, label_statistics.edge_label_probability);
            detail::bin_read(in, label_statistics.vertex_label_entropy);
            detail::bin_read(in, label_statistics.edge_label_entropy);

            in.close();
        }

        // Rebuild incidence list and edge_index_map from deserialized graph
        BuildIncidenceList();

        // --- 2. Triangles ---
        {
            std::ifstream in(index_dir + "/triangles.bin", std::ios::binary);
            if (!in) throw std::runtime_error("Cannot open " + index_dir + "/triangles.bin");

            size_t n;
            detail::bin_read(in, n);
            local_triangles.resize(n);
            for (size_t i = 0; i < n; i++) {
                size_t m;
                detail::bin_read(in, m);
                local_triangles[i].resize(m);
                for (auto& [a,b,c] : local_triangles[i]) {
                    detail::bin_read(in, a);
                    detail::bin_read(in, b);
                    detail::bin_read(in, c);
                }
            }
            in.close();
        }

        // --- 3. Four-cycles ---
        {
            std::ifstream in(index_dir + "/four_cycles.bin", std::ios::binary);
            if (in) {
                size_t n;
                detail::bin_read(in, n);
                local_four_cycles.resize(n);
                for (size_t i = 0; i < n; i++) {
                    size_t m;
                    detail::bin_read(in, m);
                    local_four_cycles[i].reserve(m);
                    for (size_t j = 0; j < m; j++) {
                        int e0,e1,e2,e3,d0,d1;
                        detail::bin_read(in, e0);
                        detail::bin_read(in, e1);
                        detail::bin_read(in, e2);
                        detail::bin_read(in, e3);
                        detail::bin_read(in, d0);
                        detail::bin_read(in, d1);
                        local_four_cycles[i].emplace_back(
                            FourMotif{{e0,e1,e2,e3},{d0,d1}});
                    }
                }
                in.close();
            }
        }

        deser_timer.Stop();
        std::cout << "[Perf] DeserializeIndexTime: " << deser_timer.GetTime() << "ms" << std::endl;
    }

} }
