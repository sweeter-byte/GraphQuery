#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <stdexcept>
#include <mutex>
#include <omp.h>

// Must define these before Graph.h since it defines globals in namespace GraphLib.
// We use a separate compilation unit so these globals are defined exactly once.
#include "Base/Metrics.h"
#include "Base/Timer.h"
#include "DataStructure/Graph.h"
#include "SpecialSubgraphs/SmallCycle.h"
#include "SubgraphMatching/DataGraph.h"
#include "SubgraphMatching/PatternGraph.h"
#include "SubgraphMatching/CandidateSpace.h"
#include "SubgraphMatching/CandidateFilter.h"
#include "SubgraphCounting/Option.h"
#include "SubgraphCounting/CardinalityEstimation.h"

namespace py = pybind11;
using namespace GraphLib;
using SubgraphMatching::DataGraph;
using SubgraphMatching::PatternGraph;
using SubgraphMatching::CandidateSpace;

class FastestWrapper {
private:
    DataGraph data_graph_;
    CardinalityEstimation::CardEstOption opt_;
    bool loaded_ = false;
    std::mutex estimate_mutex_;

public:
    FastestWrapper() {
        opt_.structure_filter = SubgraphMatching::FOURCYCLE_SAFETY;
    }

    void LoadDataGraphAndIndex(const std::string& dataset_path, const std::string& index_dir) {
        // If index_dir is non-empty and contains graph.bin, deserialize
        if (!index_dir.empty()) {
            std::ifstream test(index_dir + "/graph.bin", std::ios::binary);
            if (test.good()) {
                test.close();
                std::cout << "[FastestCore] Deserializing index from: " << index_dir << std::endl;
                data_graph_.DeserializeIndex(index_dir);
                loaded_ = true;
                std::cout << "[FastestCore] Index loaded. V=" << data_graph_.GetNumVertices()
                          << " E=" << data_graph_.GetNumEdges() << std::endl;
                return;
            }
        }

        // Fallback: load from .graph file and preprocess
        std::cout << "[FastestCore] Loading data graph from: " << dataset_path << std::endl;
        data_graph_.LoadLabeledGraph(dataset_path);
        data_graph_.Preprocess();

        GraphLib::incident_edges_size = data_graph_.GetNumVertices() * 0.01;

        if (opt_.structure_filter >= SubgraphMatching::FOURCYCLE_SAFETY)
            data_graph_.data_EnumerateLocalFourCycles();
        if (opt_.structure_filter >= SubgraphMatching::TRIANGLE_SAFETY)
            data_graph_.EnumerateLocalTriangles();

        loaded_ = true;
        std::cout << "[FastestCore] Data graph loaded and preprocessed. V=" << data_graph_.GetNumVertices()
                  << " E=" << data_graph_.GetNumEdges() << std::endl;
    }

    void SetOption(int num_threads, int ub_initial, const std::string& structure_filter) {
        GraphLib::num_threads = num_threads;
        GraphLib::group_size = 4 * num_threads;
        opt_.ub_initial = ub_initial;
        if (structure_filter == "X" || structure_filter == "none")
            opt_.structure_filter = SubgraphMatching::NO_STRUCTURE_FILTER;
        else if (structure_filter == "3" || structure_filter == "triangle")
            opt_.structure_filter = SubgraphMatching::TRIANGLE_SAFETY;
        else if (structure_filter == "4" || structure_filter == "fourcycle")
            opt_.structure_filter = SubgraphMatching::FOURCYCLE_SAFETY;
    }

    py::dict EstimatePrefix(const py::dict& prefix_payload) {
        if (!loaded_) {
            throw std::runtime_error("Data graph not loaded. Call load_data_graph_and_index first.");
        }

        // Parse the prefix payload dict into vectors for LoadGraph
        int n_v = prefix_payload["num_vertices"].cast<int>();
        int n_e = prefix_payload["num_edges"].cast<int>();

        py::list vertices = prefix_payload["vertices"].cast<py::list>();
        py::list edges = prefix_payload["edges"].cast<py::list>();

        std::vector<int> vertex_labels(n_v, 0);
        for (auto& v : vertices) {
            py::dict vd = v.cast<py::dict>();
            int id = vd["id"].cast<int>();
            int label = vd["label"].cast<int>();
            vertex_labels[id] = label;
        }

        std::vector<std::pair<int,int>> edge_pairs;
        std::vector<int> edge_labels_vec;
        edge_pairs.reserve(n_e);
        edge_labels_vec.reserve(n_e);
        for (auto& e : edges) {
            py::dict ed = e.cast<py::dict>();
            int src = ed["source"].cast<int>();
            int tgt = ed["target"].cast<int>();
            int el = ed.contains("label") ? ed["label"].cast<int>() : 0;
            edge_pairs.push_back({src, tgt});
            edge_labels_vec.push_back(el);
        }

        int requested_omp_threads = prefix_payload.contains("omp_threads") ? prefix_payload["omp_threads"].cast<int>() : GraphLib::num_threads;

        double est = 0.0;
        dict cpp_result;
        {
            // Release the GIL during heavy C++ work to prevent deadlocks across Python async threads
            py::gil_scoped_release release;

            // Dynamically set OpenMP threads for this execution block
            omp_set_num_threads(requested_omp_threads);
            int prev_global_threads = GraphLib::num_threads;
            GraphLib::num_threads = requested_omp_threads;

            // Build the PatternGraph in memory
            auto prefix_graph = std::make_unique<PatternGraph>();
            prefix_graph->LoadGraph(vertex_labels, edge_pairs, edge_labels_vec);
            prefix_graph->ProcessPattern(data_graph_);
            prefix_graph->EnumerateLocalTriangles();
            prefix_graph->query_EnumerateLocalFourCycles();

            // Copy opt_ to avoid race conditions when modifying limits concurrently
            CardinalityEstimation::CardEstOption local_opt = opt_;
            local_opt.MAX_QUERY_VERTEX = std::max(local_opt.MAX_QUERY_VERTEX, prefix_graph->GetNumVertices());
            local_opt.MAX_QUERY_EDGE = std::max(local_opt.MAX_QUERY_EDGE, prefix_graph->GetNumEdges());

            // Run the estimation
            CardinalityEstimation::FaSTestCardinalityEstimation estimator(&data_graph_, local_opt);
            est = estimator.EstimateEmbeddings(prefix_graph.get());
            cpp_result = estimator.GetResult();

            // Restore global threads (though concurrent calls might step on this, it's safer to restore)
            GraphLib::num_threads = prev_global_threads;
        }

        // Re-acquire GIL automatically out of scope, build result dict
        py::dict result;
        result["estimated_cardinality"] = est;

        // Extract timing info from the internal result
        auto extract_double = [&](const std::string& key) {
            if (cpp_result.find(key) != cpp_result.end()) {
                try { result[py::str(key)] = std::any_cast<double>(cpp_result[key]); }
                catch (...) {}
            }
        };
        extract_double("CSBuildTime");
        extract_double("TreeCountTime");
        extract_double("TreeSampleTime");
        extract_double("GraphSampleTime");
        extract_double("QueryTime");

        return result;
    }

    bool IsLoaded() const { return loaded_; }

    int GetNumVertices() const {
        return loaded_ ? data_graph_.GetNumVertices() : 0;
    }

    int GetNumEdges() const {
        return loaded_ ? data_graph_.GetNumEdges() : 0;
    }
};

PYBIND11_MODULE(fastest_core, m) {
    m.doc() = "FaSTest Cardinality Estimation Engine - Pybind11 Interface";

    py::class_<FastestWrapper>(m, "FastestEstimator")
        .def(py::init<>())
        .def("load_data_graph_and_index", &FastestWrapper::LoadDataGraphAndIndex,
             py::arg("dataset_path"), py::arg("index_dir") = "",
             "Load a data graph and its prebuilt index into memory")
        .def("set_option", &FastestWrapper::SetOption,
             py::arg("num_threads") = 4, py::arg("ub_initial") = 100000,
             py::arg("structure_filter") = "4",
             "Configure estimation options")
        .def("estimate_prefix", &FastestWrapper::EstimatePrefix,
             py::arg("prefix_payload"),
             "Estimate cardinality for a prefix subgraph given as a dict")
        .def("is_loaded", &FastestWrapper::IsLoaded)
        .def("get_num_vertices", &FastestWrapper::GetNumVertices)
        .def("get_num_edges", &FastestWrapper::GetNumEdges);
}
