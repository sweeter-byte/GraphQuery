#include <iostream>
#include <set>
#include <future>
#include <chrono>
#include <optional>
#include <cstring>
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

using namespace std;
using namespace GraphLib;

std::set<std::string> scientific_type_results = {"#CandTree"};
std::set<std::string> double_type_results = {
     "Est", "CSBuildTime", "TreeCountTime", "TreeSampleTime", "GraphSampleTime", "QueryTime"
};
std::set<std::string> longlong_type_results = {};
std::vector<std::string> print_order = {
    "#CSVertex", "#CSEdge", "#CandTree", "#TreeTrials", "#TreeSuccess", "Est",
    "CSBuildTime", "TreeCountTime", "TreeSampleTime", "GraphSampleTime", "QueryTime"
};

std::vector<dict> results;
std::string query_path;
Timer timer;
std::vector<PatternGraph*> pattern_graphs;
std::deque<std::string> query_names;
double total_time = 0.0;

struct ProcessResult {
    dict query_result;
    double est;
};

void read_ans(const std::string& dataset) {
    std::string ans_file_name = query_path;
    cout << "Reading from: " << ans_file_name << endl;
    ifstream ans_in(ans_file_name);
    if (!ans_in) {
        cout << "Error: Unable to open file " << ans_file_name << endl;
        return;
    }
    while (!ans_in.eof()) {
        string name;
        ans_in >> name;
        if (name.empty()) continue;
        name = "../dataset/" + dataset + "/query_graph/" + name;
        query_names.push_back(name);
    }
}

void read_filter_option(const string& opt, const string &filter, CardinalityEstimation::CardEstOption& option) {
    if (opt.substr(2) == "STRUCTURE") {
        if (filter == "X") option.structure_filter = SubgraphMatching::NO_STRUCTURE_FILTER;
        else if (filter == "3") option.structure_filter = SubgraphMatching::TRIANGLE_SAFETY;
        else if (filter == "4") option.structure_filter = SubgraphMatching::FOURCYCLE_SAFETY;
    }
}

int32_t main(int argc, char *argv[]) {
    string dataset = "wordnet";
    GraphLib::num_threads = 4;         // 默认值
    GraphLib::group_size = 4 * GraphLib::num_threads;         // 默认值
    GraphLib::incident_edges_size = 50000; // 默认值



    CardinalityEstimation::CardEstOption opt;
    char flag = 'F';
    char group = 'F';
    char do_query = 'T';
    bool build_index_mode = false;
    string index_output_dir;
    for (int i = 1; i < argc; ++i) {
        if (argv[i][0] == '-') {
            // 处理短参数（单破折号）
            if (argv[i][1] != '-') {
                switch (argv[i][1]) {
                    case 'd': dataset = argv[++i]; break;
                    case 'q': query_path = argv[++i]; break;
                    case 'K': opt.ub_initial = atoi(argv[++i]); break;
                    case 'x': do_query = 'F'; break;
                }
            }
            // 处理长参数（双破折号）
            else {
                const char* arg = argv[i] + 2;  // 跳过"--"
                if (strcmp(arg, "threads") == 0) {
                    GraphLib::num_threads = atoi(argv[++i]);
                } else if (strcmp(arg, "group_size") == 0) {
                    GraphLib::group_size = atoi(argv[++i]);
                    group = 'T';
                } else if (strcmp(arg, "incident_edges_size") == 0) {
                    GraphLib::incident_edges_size = atoi(argv[++i]);
                    flag = 'T';
                } else if (strcmp(arg, "STRUCTURE") == 0) {  // 保留原有逻辑
                    read_filter_option(string(argv[i]), string(argv[++i]), opt);
                } else if (strcmp(arg, "build-index") == 0) {
                    build_index_mode = true;
                } else if (strcmp(arg, "index-dir") == 0) {
                    index_output_dir = argv[++i];
                } else {
                    cerr << "未知参数: " << argv[i] << endl;
                    exit(1);
                }
            }
        }
    }

    if (query_path.empty()) {
        query_path = "../dataset/"+dataset+"/"+dataset+"_ans.txt";
    }

    
    
    string data_path = "../dataset/"+dataset+"/"+dataset+".graph";
    read_ans(dataset);
    DataGraph D; 
    
    std::cout << "Begin Indexing ..." << std::endl;
    D.LoadLabeledGraph(data_path);
    D.Preprocess();
    if (flag == 'F') GraphLib::incident_edges_size = D.GetNumVertices() * 0.01; //(0.01 - 0.02)
    if (group == 'F') GraphLib::group_size = 4 * GraphLib::num_threads;

    // 验证参数
    cout << "[Config] threads=" << GraphLib::num_threads 
         << " group_size=" << GraphLib::group_size
         << " incident_edges_size=" << GraphLib::incident_edges_size << endl;
    //std::cout << "Tasking:" << std::endl;
    if (opt.structure_filter >= SubgraphMatching::FOURCYCLE_SAFETY) D.data_EnumerateLocalFourCycles(); //数据图使用并行化处理
    if (opt.structure_filter >= SubgraphMatching::TRIANGLE_SAFETY) D.EnumerateLocalTriangles();
    opt.MAX_QUERY_VERTEX = 12;
    opt.MAX_QUERY_EDGE = 4;
    std::cout << "End Indexing ..." << std::endl;

    // --build-index mode: serialize index and exit
    if (build_index_mode) {
        if (index_output_dir.empty()) {
            index_output_dir = "../dataset/" + dataset + "/index";
        }
        std::cout << "Serializing index to: " << index_output_dir << std::endl;
        D.SerializeIndex(index_output_dir);
        std::cout << "Index built successfully." << std::endl;
        return 0;
    }

    if (do_query == 'F') return 0;
    for (size_t i = 0; i < query_names.size(); i++) {
        auto P = std::make_unique<PatternGraph>(); 
        string query_name = query_names[i];
        
        P->LoadLabeledGraph(query_name);
        P->ProcessPattern(D);
        P->EnumerateLocalTriangles();
        P->query_EnumerateLocalFourCycles(); //查询图使用串行处理
        opt.MAX_QUERY_VERTEX = std::max(opt.MAX_QUERY_VERTEX, P->GetNumVertices());
        opt.MAX_QUERY_EDGE = std::max(opt.MAX_QUERY_EDGE, P->GetNumEdges());
        
        cout << "Start Processing " << query_name << endl;
        try {
            CardinalityEstimation::FaSTestCardinalityEstimation local_estimator(&D, opt);
            double est = local_estimator.EstimateEmbeddings(P.get()); // 获取原始指针
    
            dict query_result = local_estimator.GetResult();
            query_result["Est"] = est;
        
            for (auto &key : print_order) {
                if (query_result.find(key) == query_result.end()) continue;
                    any value = query_result[key];
                if (double_type_results.count(key)) {
                    printf("  [Result] %-20s: %.04lf\n", key.c_str(), any_cast<double>(value));
                } else if (scientific_type_results.count(key)) {
                    printf("  [Result] %-20s: %.04g\n", key.c_str(), any_cast<double>(value));
                } else if (longlong_type_results.count(key)) {
                    printf("  [Result] %-20s: %lld\n", key.c_str(), any_cast<long long>(value));
                } else {
                    printf("  [Result] %-20s: %d\n", key.c_str(), any_cast<int>(value));
                }
            }
            results.push_back(query_result);
            cout << query_name << " Finished!\n";
        } catch (...) {
            cerr << "Error processing " << query_name << ". Skipping." << endl;
            continue;
        }
    }
    
    timer.Stop();
    cout << fixed << setprecision(2) << "Total Time: " << Total(results, "QueryTime") << "ms\n";

    return 0;
}