// Direct bitmap/sign five-position row accumulator for a 5-bit-wide presence
// memory (Architecture B): each cycle's five presence bits arrive as one
// word, so no presence byte cursor is needed. Otherwise identical to
// ternary_bitcos_stream5_direct_accum: presence bits gate each activation and
// compact sign bits select +/- activations for present weights only.
//
// Inputs supply the presence word and the current and next sign byte. SRAM,
// byte registers, and refill control remain outside this module.
module ternary_bitcos_stream5_directbank_accum #(
    parameter int ACT_W = 8,
    parameter int ACC_W = 24
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    start,
    input  logic [2:0]              initial_sign_offset,
    input  logic                    valid,
    input  logic                    last,
    input  logic [5*ACT_W-1:0]      activations,
    input  logic [4:0]              presence,
    input  logic [7:0]              current_sign_byte,
    input  logic [7:0]              next_sign_byte,
    output logic                    advance_sign_byte,
    output logic [2:0]              sign_offset,
    output logic signed [ACC_W-1:0] dot,
    output logic                    done
);
    logic [15:0] sign_pair;
    logic [4:0] sign_window;
    wire [2:0] rank [0:5];
    wire [5*ACC_W-1:0] contributions;
    logic [3:0] sign_total;
    logic signed [ACC_W-1:0] partial;
    logic signed [ACC_W-1:0] acc;

    assign sign_pair = {next_sign_byte, current_sign_byte};
    assign sign_window = (sign_pair >> sign_offset);
    assign rank[0] = 3'd0;

    genvar i;
    generate
        for (i = 0; i < 5; i = i + 1) begin : gen_lane
            assign rank[i+1] = rank[i] + {2'b00, presence[i]};
            wire negative = sign_window[rank[i]];
            wire signed [ACT_W-1:0] a =
                $signed(activations[i*ACT_W +: ACT_W]);
            wire signed [ACC_W-1:0] a_ext = a;
            wire signed [ACC_W-1:0] contribution =
                !presence[i] ? '0 :
                negative ? -a_ext : a_ext;
            assign contributions[i*ACC_W +: ACC_W] = contribution;
        end
    endgenerate

    signed_adder_tree #(.LANES(5), .ACC_W(ACC_W)) reduce (
        .inputs(contributions),
        .sum(partial)
    );

    assign sign_total = {1'b0, sign_offset} + {1'b0, rank[5]};
    assign advance_sign_byte = valid && sign_total[3];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sign_offset <= '0;
            acc <= '0;
            dot <= '0;
            done <= 1'b0;
        end else begin
            done <= 1'b0;
            if (start) begin
                sign_offset <= initial_sign_offset;
                acc <= '0;
            end else if (valid) begin
                sign_offset <= sign_total[2:0];
                if (last) begin
                    dot <= acc + partial;
                    acc <= '0;
                    done <= 1'b1;
                end else begin
                    acc <= acc + partial;
                end
            end
        end
    end
endmodule
